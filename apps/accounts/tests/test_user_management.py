"""The invariants that keep account administration from locking people out."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.permissions import OWNER_ROLE, PRODUCER_ROLE, Perm
from apps.accounts.repositories import MembershipRepository, RoleRepository
from apps.accounts.services import (
    AccessError,
    MembershipService,
    RoleService,
    UserAdminService,
)

from .factories import (
    PASSWORD,
    VIEWER_ROLE,
    add_member,
    make_account,
    make_role,
    make_system_admin,
    make_user,
)


class AddUserTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.viewer_role = RoleRepository.get_by_name(self.account, VIEWER_ROLE)
        self.client.force_login(self.owner)

    def test_a_new_user_is_active_immediately(self):
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "email": "new@example.com",
                "full_name": "New Person",
                "role": self.viewer_role.pk,
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )

        self.assertRedirects(response, reverse("accounts:user_list"))
        user = User.objects.get(email="new@example.com")
        self.assertTrue(user.is_active)
        self.assertTrue(user.must_change_password)

        self.client.logout()
        self.assertTrue(self.client.login(username=user.email, password=PASSWORD))

    def test_an_existing_email_gains_a_membership_not_a_second_user(self):
        existing = make_user("existing@example.com")

        self.client.post(
            reverse("accounts:user_create"),
            {"email": existing.email, "role": self.viewer_role.pk},
        )

        self.assertEqual(User.objects.filter(email=existing.email).count(), 1)
        self.assertIsNotNone(MembershipRepository.get(existing, self.account))

    def test_adding_the_same_user_twice_is_refused(self):
        member = make_user("member@example.com")
        add_member(self.account, member, VIEWER_ROLE)

        self.client.post(
            reverse("accounts:user_create"),
            {"email": member.email, "role": self.viewer_role.pk},
        )

        self.assertEqual(
            MembershipRepository.for_account(self.account)
            .filter(user=member)
            .count(),
            1,
        )


class PrivilegeEscalationTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.producer = make_user("producer@example.com")
        add_member(self.account, self.producer, PRODUCER_ROLE)
        # Producer administers users and roles, but still cannot override the budget
        # cap — the permission they must not be able to hand out.
        producer_role = RoleRepository.get_by_name(self.account, PRODUCER_ROLE)
        RoleRepository.update(
            producer_role,
            permissions=list(producer_role.codenames)
            + [Perm.ACCOUNT_MANAGE_USERS, Perm.ACCOUNT_MANAGE_ROLES],
        )

    def test_a_role_cannot_be_granted_permissions_the_granter_lacks(self):
        producer_codenames = RoleRepository.get_by_name(
            self.account, PRODUCER_ROLE
        ).codenames

        with self.assertRaises(AccessError):
            RoleService.create(
                account=self.account,
                name="Overspender",
                description="",
                codenames=[Perm.STEP_OVERRIDE_BUDGET],
                granted_by_codenames=producer_codenames,
            )

    def test_a_user_cannot_be_assigned_a_role_stronger_than_the_assigner(self):
        owner_role = RoleRepository.get_by_name(self.account, OWNER_ROLE)
        producer_codenames = RoleRepository.get_by_name(
            self.account, PRODUCER_ROLE
        ).codenames
        newcomer = make_user("newcomer@example.com")

        with self.assertRaises(AccessError):
            MembershipService.add_user(
                account=self.account,
                email=newcomer.email,
                full_name="",
                password=None,
                role=owner_role,
                invited_by=self.producer,
                granted_by_codenames=producer_codenames,
            )

    def test_the_form_only_offers_permissions_the_editor_holds(self):
        self.client.force_login(self.producer)

        response = self.client.get(reverse("accounts:role_create"))

        offered = {
            codename for codename, _ in response.context["form"].fields["permissions"].choices
        }
        self.assertNotIn(Perm.STEP_OVERRIDE_BUDGET, offered)
        self.assertIn(Perm.VIDEO_CREATE, offered)


class LastAdministratorTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.owner_membership = MembershipRepository.get(self.owner, self.account)

    def test_the_account_owner_cannot_be_removed(self):
        with self.assertRaises(AccessError):
            MembershipService.remove(self.owner_membership, self.owner)

    def test_the_account_owner_cannot_be_deactivated(self):
        with self.assertRaises(AccessError):
            MembershipService.set_active(self.owner_membership, False, self.owner)

    def test_the_owner_cannot_drop_to_a_role_without_user_management(self):
        viewer_role = RoleRepository.get_by_name(self.account, VIEWER_ROLE)

        with self.assertRaises(AccessError):
            MembershipService.change_role(
                self.owner_membership,
                viewer_role,
                self.owner,
                RoleRepository.get_by_name(self.account, OWNER_ROLE).codenames,
            )

    def test_the_last_admin_role_cannot_lose_user_management(self):
        owner_role = RoleRepository.get_by_name(self.account, OWNER_ROLE)

        with self.assertRaises(AccessError):
            RoleService.update(
                owner_role,
                name=owner_role.name,
                description="",
                codenames=[Perm.VIDEO_VIEW],
                granted_by_codenames=owner_role.codenames,
                actor=self.owner,
            )

    def test_a_second_admin_makes_the_first_one_removable(self):
        deputy = make_user("deputy@example.com")
        deputy_role = make_role(
            self.account, "Deputy", [Perm.ACCOUNT_MANAGE_USERS, Perm.VIDEO_VIEW]
        )
        deputy_membership = MembershipRepository.create(
            user=deputy, account=self.account, role=deputy_role
        )

        # The deputy is no longer the last administrator, so removing them is fine.
        MembershipService.remove(deputy_membership, self.owner)

        self.assertIsNone(MembershipRepository.get(deputy, self.account))


class RoleLifecycleTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.client.force_login(self.owner)

    def test_a_role_in_use_cannot_be_deleted(self):
        member = make_user("member@example.com")
        add_member(self.account, member, VIEWER_ROLE)
        role = RoleRepository.get_by_name(self.account, VIEWER_ROLE)

        with self.assertRaises(AccessError):
            RoleService.delete(role)

    def test_an_unused_role_can_be_deleted(self):
        role = make_role(self.account, "Spare", [Perm.VIDEO_VIEW])

        response = self.client.post(reverse("accounts:role_delete", args=[role.pk]))

        self.assertRedirects(response, reverse("accounts:role_list"))
        self.assertIsNone(RoleRepository.get_or_none(role.pk))

    def test_duplicate_role_names_in_one_account_are_refused(self):
        owner_codenames = RoleRepository.get_by_name(
            self.account, OWNER_ROLE
        ).codenames

        with self.assertRaises(AccessError):
            RoleService.create(
                account=self.account,
                name=VIEWER_ROLE,
                description="",
                codenames=[Perm.VIDEO_VIEW],
                granted_by_codenames=owner_codenames,
            )

    def test_a_role_in_another_account_is_not_reachable(self):
        other = make_account(make_user("other@example.com"), "Other Studio")
        foreign_role = make_role(other, "Foreign", [Perm.VIDEO_VIEW])

        response = self.client.get(
            reverse("accounts:role_edit", args=[foreign_role.pk])
        )

        self.assertEqual(response.status_code, 404)


class SystemAdminUserTests(TestCase):
    def setUp(self):
        self.admin = make_system_admin()

    def test_the_last_system_admin_cannot_be_demoted(self):
        other = make_system_admin("second@example.com")

        with self.assertRaises(AccessError):
            # Demote the other one first, leaving self.admin as the only admin...
            UserAdminService.set_system_admin(other, False, self.admin)
            UserAdminService.set_system_admin(self.admin, False, other)

    def test_a_system_admin_cannot_deactivate_themselves(self):
        with self.assertRaises(AccessError):
            UserAdminService.set_active(self.admin, False, self.admin)

    def test_a_password_reset_forces_a_change(self):
        user = make_user("someone@example.com")

        UserAdminService.reset_password(user, "brand-new-passphrase-7")

        user.refresh_from_db()
        self.assertTrue(user.check_password("brand-new-passphrase-7"))
        self.assertTrue(user.must_change_password)
