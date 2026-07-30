"""Permission resolution, the system-admin bypass, and account switching."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.access import SESSION_ACCOUNT_KEY
from apps.accounts.permissions import ALL_CODENAMES, OWNER_ROLE, PRODUCER_ROLE, Perm
from apps.accounts.repositories import RoleRepository

from .factories import (
    PASSWORD,
    VIEWER_ROLE,
    add_member,
    make_account,
    make_system_admin,
    make_user,
)


class PermissionResolutionTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)

    def test_role_permissions_reach_the_request(self):
        viewer = make_user("viewer@example.com")
        add_member(self.account, viewer, VIEWER_ROLE)
        self.client.force_login(viewer)

        response = self.client.get(reverse("videos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can"]["video_view"])
        self.assertFalse(response.context["can"]["video_create"])
        self.assertFalse(response.context["can"]["step_approve_paid"])

    def test_owner_holds_every_permission(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("videos:list"))
        self.assertTrue(all(response.context["can"].values()))

    def test_producer_cannot_override_the_budget(self):
        producer = make_user("producer@example.com")
        add_member(self.account, producer, PRODUCER_ROLE)
        self.client.force_login(producer)

        can = self.client.get(reverse("videos:list")).context["can"]

        self.assertTrue(can["step_approve_paid"])
        self.assertFalse(can["step_override_budget"])
        self.assertFalse(can["account_manage_users"])

    def test_stale_codename_grants_nothing(self):
        """Role permissions are JSON, so a codename can outlive the catalog."""
        role = RoleRepository.get_by_name(self.account, VIEWER_ROLE)
        RoleRepository.update(
            role, permissions=[Perm.VIDEO_VIEW, "video.teleport"]
        )
        self.assertEqual(role.codenames, frozenset({Perm.VIDEO_VIEW}))

    def test_anonymous_is_redirected_to_login(self):
        for name in ("videos:list", "templates:list", "accounts:user_list"):
            with self.subTest(url=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])

    def test_member_of_no_account_is_sent_to_the_dead_end(self):
        stranger = make_user("nobody@example.com")
        self.client.force_login(stranger)
        response = self.client.get(reverse("videos:list"))
        self.assertRedirects(response, reverse("accounts:no_account"))

    def test_inactive_membership_grants_nothing(self):
        viewer = make_user("dormant@example.com")
        membership = add_member(self.account, viewer, VIEWER_ROLE)
        membership.is_active = False
        membership.save()

        self.client.force_login(viewer)
        response = self.client.get(reverse("videos:list"))

        self.assertRedirects(response, reverse("accounts:no_account"))

    def test_inactive_user_cannot_sign_in(self):
        locked = make_user("locked@example.com", is_active=False)
        add_member(self.account, locked, VIEWER_ROLE)

        signed_in = self.client.login(username=locked.email, password=PASSWORD)

        self.assertFalse(signed_in)


class SystemAdminTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        self.account = make_account(self.owner)
        self.admin = make_system_admin()

    def test_system_admin_holds_the_whole_catalog(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("console:account_enter", args=[self.account.pk]))

        can = self.client.get(reverse("videos:list")).context["can"]

        self.assertEqual(
            {code for code, granted in can.items() if granted},
            {code.replace(".", "_") for code in ALL_CODENAMES},
        )

    def test_system_admin_can_enter_an_account_without_a_membership(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("console:account_enter", args=[self.account.pk])
        )

        self.assertRedirects(response, reverse("videos:list"))
        self.assertEqual(self.client.session[SESSION_ACCOUNT_KEY], self.account.pk)

    def test_console_is_closed_to_ordinary_users(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("console:dashboard"))
        self.assertEqual(response.status_code, 403)


class AccountSwitchingTests(TestCase):
    def setUp(self):
        self.user = make_user("multi@example.com")
        self.first = make_account(self.user, "First Studio")
        self.other_owner = make_user("other@example.com")
        self.second = make_account(self.other_owner, "Second Studio")

    def test_switching_to_a_non_member_account_is_a_404(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:switch", args=[self.second.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.session[SESSION_ACCOUNT_KEY], self.first.pk)

    def test_switching_to_a_member_account_changes_the_active_one(self):
        add_member(self.second, self.user, VIEWER_ROLE)
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("accounts:switch", args=[self.second.pk])
        )

        self.assertRedirects(response, reverse("videos:list"))
        self.assertEqual(self.client.session[SESSION_ACCOUNT_KEY], self.second.pk)

    def test_permissions_follow_the_active_account(self):
        add_member(self.second, self.user, VIEWER_ROLE)
        self.client.force_login(self.user)

        owner_can = self.client.get(reverse("videos:list")).context["can"]
        self.assertTrue(owner_can["account_manage_users"])

        self.client.post(reverse("accounts:switch", args=[self.second.pk]))
        viewer_can = self.client.get(reverse("videos:list")).context["can"]

        self.assertFalse(viewer_can["account_manage_users"])
        self.assertFalse(viewer_can["video_create"])
        self.assertTrue(viewer_can["video_view"])

    def test_switching_is_post_only(self):
        add_member(self.second, self.user, VIEWER_ROLE)
        self.client.force_login(self.user)

        self.client.get(reverse("accounts:switch", args=[self.second.pk]))

        self.assertEqual(self.client.session[SESSION_ACCOUNT_KEY], self.first.pk)

    def test_a_revoked_membership_falls_back_to_a_remaining_one(self):
        membership = add_member(self.second, self.user, VIEWER_ROLE)
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:switch", args=[self.second.pk]))

        membership.delete()
        response = self.client.get(reverse("videos:list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["account"].pk, self.first.pk)


class OwnerRoleTests(TestCase):
    def test_a_new_account_gets_the_three_default_roles(self):
        owner = make_user("owner@example.com")
        account = make_account(owner)

        names = set(account.roles.values_list("name", flat=True))

        self.assertEqual(names, {OWNER_ROLE, PRODUCER_ROLE, VIEWER_ROLE})
        self.assertEqual(
            RoleRepository.get_by_name(account, OWNER_ROLE).codenames, ALL_CODENAMES
        )
