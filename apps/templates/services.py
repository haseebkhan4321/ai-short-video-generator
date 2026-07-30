"""Business logic for templates. Views call these; these call the repository."""
from decimal import Decimal

from django.db.models import Count, Q, Sum

from .repositories import TemplateRepository


class TemplateService:
    @staticmethod
    def list_templates(account):
        return TemplateRepository.for_account(account)

    @staticmethod
    def list_templates_with_stats(account):
        """Templates annotated with video count and total spend for the list view."""
        return TemplateRepository.for_account(account).annotate(
            video_count=Count("videos", distinct=True),
            total_cost=Sum("videos__total_cost_usd"),
        )

    @staticmethod
    def get_template(template_id, account):
        """Scoped lookup: returns None for a template in another account, so the
        view raises 404 rather than leaking its existence."""
        return TemplateRepository.get_in_account(template_id, account)

    @staticmethod
    def cost_summary(template):
        """Aggregate spend and video counts across all of a template's videos."""
        agg = template.videos.aggregate(
            total=Sum("total_cost_usd"),
            count=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
            failed=Count("id", filter=Q(status="failed")),
        )
        return {
            "total_cost_usd": agg["total"] or Decimal("0"),
            "video_count": agg["count"] or 0,
            "completed_count": agg["completed"] or 0,
            "failed_count": agg["failed"] or 0,
        }

    @staticmethod
    def create_template(account, data):
        return TemplateRepository.create(
            account=account,
            name=data["name"],
            niche=data.get("niche", ""),
            description=data.get("description", ""),
            style_prompt=data.get("style_prompt", ""),
            narrator_voice=data.get("narrator_voice", ""),
            language=data.get("language", "en"),
        )

    @staticmethod
    def update_template(template, data):
        return TemplateRepository.update(
            template,
            name=data["name"],
            niche=data.get("niche", ""),
            description=data.get("description", ""),
            style_prompt=data.get("style_prompt", ""),
            narrator_voice=data.get("narrator_voice", ""),
            language=data.get("language", "en"),
        )

    @staticmethod
    def delete_template(template):
        TemplateRepository.delete(template)
