"""Seeds the system default roles.

Required by both environments: `Account` creation clones these, so without them a
new account has no roles and its owner has no permissions.
"""
from apps.accounts import permissions as perms
from apps.accounts.permissions import DEFAULT_ROLES
from apps.accounts.repositories import RoleRepository

from .base import Seeder


class RoleSeeder(Seeder):
    name = "System default roles"

    def run(self, refresh=False, **options):
        """``refresh`` re-applies the catalog to existing defaults.

        Off by default: an operator may have edited a default at
        ``/console/default-roles/``, and a seeder should not quietly undo that.
        """
        for spec in DEFAULT_ROLES:
            wanted = perms.clean(spec["permissions"])
            role = RoleRepository.get_by_name(None, spec["name"])

            if role is None:
                RoleRepository.create(
                    account=None,
                    name=spec["name"],
                    description=spec["description"],
                    permissions=wanted,
                    is_system_default=True,
                )
                self.created(f"{spec['name']} ({len(wanted)} permissions)")
            elif refresh and (
                sorted(role.codenames) != sorted(wanted)
                or role.description != spec["description"]
            ):
                RoleRepository.update(
                    role, description=spec["description"], permissions=wanted
                )
                self.updated(f"{spec['name']} ({len(wanted)} permissions)")
            else:
                self.existed(spec["name"])

        return RoleRepository.system_defaults()
