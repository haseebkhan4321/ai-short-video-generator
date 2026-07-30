"""The public account-request flow and system-admin approval."""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Account, AccountRequest, RequestStatus, User
from apps.accounts.permissions import ALL_CODENAMES, OWNER_ROLE
from apps.accounts.repositories import MembershipRepository
from apps.accounts.services import AccessError, AccountRequestService

from .factories import PASSWORD, make_system_admin, make_user

REQUEST_FORM = {
    "full_name": "Ada Lovelace",
    "email": "ada@example.com",
    "account_name": "Analytical Studio",
    "password1": PASSWORD,
    "password2": PASSWORD,
    "message": "I want to make history videos.",
}


class SubmitRequestTests(TestCase):
    def test_submitting_creates_an_inactive_user_and_a_pending_request(self):
        response = self.client.post(reverse("accounts:request"), REQUEST_FORM)

        self.assertRedirects(response, reverse("accounts:request_received"))
        user = User.objects.get(email="ada@example.com")
        self.assertFalse(user.is_active)
        request_row = AccountRequest.objects.get(email="ada@example.com")
        self.assertEqual(request_row.status, RequestStatus.PENDING)
        self.assertEqual(request_row.user_id, user.pk)

    def test_a_pending_user_cannot_sign_in_yet(self):
        self.client.post(reverse("accounts:request"), REQUEST_FORM)

        signed_in = self.client.login(username="ada@example.com", password=PASSWORD)

        self.assertFalse(signed_in)

    def test_no_account_exists_before_approval(self):
        self.client.post(reverse("accounts:request"), REQUEST_FORM)
        user = User.objects.get(email="ada@example.com")
        self.assertFalse(user.owned_accounts.exists())

    def test_mismatched_passwords_are_rejected(self):
        response = self.client.post(
            reverse("accounts:request"), {**REQUEST_FORM, "password2": "different-1"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="ada@example.com").exists())

    def test_a_duplicate_email_is_rejected(self):
        make_user("ada@example.com")

        response = self.client.post(reverse("accounts:request"), REQUEST_FORM)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountRequest.objects.count(), 0)

    def test_a_second_pending_request_is_refused(self):
        self.client.post(reverse("accounts:request"), REQUEST_FORM)

        response = self.client.post(reverse("accounts:request"), REQUEST_FORM)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AccountRequest.objects.count(), 1)


class ReviewRequestTests(TestCase):
    def setUp(self):
        self.admin = make_system_admin()
        self.client.post(reverse("accounts:request"), REQUEST_FORM)
        self.request_row = AccountRequest.objects.get(email="ada@example.com")

    def _review(self, decision, note=""):
        self.client.force_login(self.admin)
        return self.client.post(
            reverse("console:request_review", args=[self.request_row.pk]),
            {"decision": decision, "note": note},
        )

    def test_approval_activates_the_user_and_builds_their_account(self):
        self._review("approve", "welcome")

        self.request_row.refresh_from_db()
        self.assertEqual(self.request_row.status, RequestStatus.APPROVED)
        self.assertEqual(self.request_row.reviewed_by_id, self.admin.pk)
        self.assertEqual(self.request_row.decision_note, "welcome")

        user = User.objects.get(email="ada@example.com")
        self.assertTrue(user.is_active)

        account = self.request_row.account
        self.assertIsNotNone(account)
        self.assertEqual(account.name, "Analytical Studio")
        self.assertEqual(account.owner_id, user.pk)

    def test_the_approved_user_signs_in_as_owner_with_the_password_they_chose(self):
        self._review("approve")
        self.client.logout()

        signed_in = self.client.login(username="ada@example.com", password=PASSWORD)

        self.assertTrue(signed_in)
        user = User.objects.get(email="ada@example.com")
        membership = MembershipRepository.for_user(user).first()
        self.assertEqual(membership.role.name, OWNER_ROLE)
        self.assertEqual(membership.role.codenames, ALL_CODENAMES)

    def test_the_approved_account_starts_with_the_default_roles(self):
        self._review("approve")
        self.request_row.refresh_from_db()

        names = set(self.request_row.account.roles.values_list("name", flat=True))

        self.assertEqual(names, {"Owner", "Producer", "Viewer"})

    def test_rejection_deletes_the_pending_user(self):
        self._review("reject", "not now")

        self.request_row.refresh_from_db()
        self.assertEqual(self.request_row.status, RequestStatus.REJECTED)
        self.assertFalse(User.objects.filter(email="ada@example.com").exists())
        self.assertIsNone(self.request_row.user_id)

    def test_a_request_cannot_be_reviewed_twice(self):
        self._review("approve")
        self.request_row.refresh_from_db()

        with self.assertRaises(AccessError):
            AccountRequestService.approve(self.request_row, self.admin)

        self.assertEqual(Account.objects.filter(name="Analytical Studio").count(), 1)

    def test_reposting_a_review_does_not_create_a_second_account(self):
        self._review("approve")

        self._review("approve")

        self.assertEqual(Account.objects.filter(name="Analytical Studio").count(), 1)

    def test_an_ordinary_user_cannot_review(self):
        outsider = make_user("outsider@example.com")
        self.client.force_login(outsider)

        response = self.client.post(
            reverse("console:request_review", args=[self.request_row.pk]),
            {"decision": "approve"},
        )

        self.assertEqual(response.status_code, 403)
        self.request_row.refresh_from_db()
        self.assertEqual(self.request_row.status, RequestStatus.PENDING)
