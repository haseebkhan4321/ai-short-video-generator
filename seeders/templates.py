"""Seeds content templates into an account."""
from apps.templates.repositories import TemplateRepository
from apps.templates.services import TemplateService

from .base import Seeder
from .data import STARTER_TEMPLATES


class TemplateSeeder(Seeder):
    name = "Templates"

    def run(self, account=None, only=None, update=False, **options):
        """``only`` is a list of template names; None means all of them."""
        if account is None:
            self.fail("A target account is required.")

        wanted = STARTER_TEMPLATES
        if only is not None and only != "all":
            names = set(only)
            wanted = [t for t in STARTER_TEMPLATES if t["name"] in names]
            missing = names - {t["name"] for t in STARTER_TEMPLATES}
            if missing:
                self.fail(f"Unknown template name(s): {', '.join(sorted(missing))}")

        built = {}
        for spec in wanted:
            existing = TemplateRepository.get_by_name(account, spec["name"])
            if existing is None:
                built[spec["name"]] = TemplateService.create_template(account, spec)
                self.created(f"{spec['name']} in {account.name}")
            elif update:
                built[spec["name"]] = TemplateService.update_template(existing, spec)
                self.updated(f"{spec['name']} in {account.name}")
            else:
                built[spec["name"]] = existing
                self.existed(f"{spec['name']} in {account.name}")

        return built
