"""The development quick sign-in.

It bypasses authentication entirely, so the guards are the whole point of these
tests: off by default, unreachable without DEBUG, and never able to sign in as a
user outside the throwaway domain even while enabled.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User

from .factories import PASSWORD, VIEWER_ROLE, add_member, make_account, make_user

# DEBUG as well as the flag: the test runner forces DEBUG off, and the view requires
# both. That is the guard working, so the tests have to opt into both.
ON = {
    "DEBUG": True,
    "DEV_LOGIN_ENABLED": True,
    "DEV_LOGIN_EMAIL_DOMAIN": "dev.local",
}


# Explicitly off rather than relying on the ambient value: a developer's own .env may
# well have this enabled, and these tests are about the disabled behaviour.
@override_settings(DEBUG=True, DEV_LOGIN_ENABLED=False)
class DevLoginDisabledTests(TestCase):
    def setUp(self):
        self.dev = make_user("owner@dev.local")

    def test_the_view_is_a_404_when_disabled(self):
        response = self.client.post(reverse("accounts:dev_login", args=[self.dev.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_no_buttons_are_rendered_when_disabled(self):
        response = self.client.get(reverse("accounts:login"))

        self.assertEqual(response.context["dev_logins"], [])
        self.assertNotIn("Development sign-in", response.content.decode())


@override_settings(**ON)
class DevLoginEnabledTests(TestCase):
    def setUp(self):
        self.dev = make_user("owner@dev.local", full_name="Olive Owner")
        self.account = make_account(self.dev, "Midnight Studio")
        self.real = make_user("someone@example.com")

    def test_it_signs_in_without_a_password(self):
        response = self.client.post(reverse("accounts:dev_login", args=[self.dev.pk]))

        self.assertRedirects(response, reverse("videos:list"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.dev.pk)

    def test_it_says_out_loud_that_no_password_was_checked(self):
        response = self.client.post(
            reverse("accounts:dev_login", args=[self.dev.pk]), follow=True
        )

        messages = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("no password" in m.lower() for m in messages), messages)

    def test_it_refuses_a_user_outside_the_dev_domain(self):
        """The guard that matters: enabling this must not expose real accounts."""
        response = self.client.post(reverse("accounts:dev_login", args=[self.real.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_it_refuses_a_deactivated_user(self):
        locked = make_user("locked@dev.local", is_active=False)

        response = self.client.post(reverse("accounts:dev_login", args=[locked.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_it_refuses_an_unknown_user(self):
        response = self.client.post(reverse("accounts:dev_login", args=[99_999]))
        self.assertEqual(response.status_code, 404)

    def test_it_is_post_only(self):
        """So a pasted link cannot sign anyone in."""
        response = self.client.get(reverse("accounts:dev_login", args=[self.dev.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_buttons_list_dev_users_with_their_roles(self):
        member = make_user("viewer@dev.local")
        add_member(self.account, member, VIEWER_ROLE)

        response = self.client.get(reverse("accounts:login"))

        emails = [e["user"].email for e in response.context["dev_logins"]]
        self.assertEqual(emails, ["owner@dev.local", "viewer@dev.local"])
        html = response.content.decode()
        self.assertIn("Development sign-in", html)
        self.assertIn("Viewer in Midnight Studio", html)
        self.assertNotIn("someone@example.com", html)

    def test_it_honours_next(self):
        target = reverse("templates:list")

        response = self.client.post(
            reverse("accounts:dev_login", args=[self.dev.pk]), {"next": target}
        )

        self.assertRedirects(response, target)

    def test_a_system_admin_with_no_account_lands_on_the_console(self):
        """Not the no-account dead end, which is correct but useless as a landing."""
        admin = make_user("admin@dev.local", is_system_admin=True)

        response = self.client.post(reverse("accounts:dev_login", args=[admin.pk]))

        self.assertRedirects(response, reverse("console:dashboard"))

    def test_normal_password_sign_in_still_works(self):
        signed_in = self.client.login(username=self.dev.email, password=PASSWORD)
        self.assertTrue(signed_in)


@override_settings(DEV_LOGIN_ENABLED=True, DEBUG=False)
class DevLoginWithoutDebugTests(TestCase):
    """Settings compute the flag as ``flag and DEBUG``, and the view re-checks
    ``DEBUG`` itself — so the bypass stays shut even if another settings file sets
    the flag directly."""

    def setUp(self):
        self.dev = make_user("owner@dev.local")

    def test_the_view_is_a_404_without_debug(self):
        response = self.client.post(reverse("accounts:dev_login", args=[self.dev.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_no_buttons_are_offered_without_debug(self):
        response = self.client.get(reverse("accounts:login"))
        self.assertEqual(response.context["dev_logins"], [])


@override_settings(**ON)
class DevLoginDomainTests(TestCase):
    def test_only_dev_domain_users_are_offered(self):
        make_user("real@example.com")
        make_user("dev@dev.local")

        response = self.client.get(reverse("accounts:login"))

        offered = {e["user"].email for e in response.context["dev_logins"]}
        self.assertEqual(offered, {"dev@dev.local"})

    def test_the_domain_is_configurable(self):
        make_user("someone@staging.invalid")

        with override_settings(DEV_LOGIN_EMAIL_DOMAIN="staging.invalid"):
            response = self.client.get(reverse("accounts:login"))

        offered = {e["user"].email for e in response.context["dev_logins"]}
        self.assertEqual(offered, {"someone@staging.invalid"})

    def test_a_lookalike_domain_is_not_accepted(self):
        """``@dev.local`` must match the end of the address, not appear anywhere."""
        impostor = make_user("dev.local@example.com")

        response = self.client.post(
            reverse("accounts:dev_login", args=[impostor.pk])
        )

        self.assertEqual(response.status_code, 404)
        self.assertFalse(User.objects.filter(pk=impostor.pk).first().is_staff)
