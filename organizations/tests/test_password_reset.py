"""Invite-claim seam (bookr-0vc): staff presets the member in admin;
the member sets their own password through an emailed token link.

No public signup: both endpoints are anonymous by necessity (the
claimer has no credentials yet), but the request endpoint never
reveals whether an address exists.
"""

import re

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from tests.factories import UserFactory

pytestmark = pytest.mark.django_db

RESET_URL = "/api/v1/auth/password-reset/"
CONFIRM_URL = "/api/v1/auth/password-reset-confirm/"


class TestRequestReset:
    def test_known_email_gets_claim_link(self):
        member = UserFactory(username="invited", email="invited@example.com")

        response = APIClient().post(RESET_URL, {"email": member.email})

        assert response.status_code == 200
        assert len(mail.outbox) == 1
        assert member.email in mail.outbox[0].to
        # The token embeds the generation second: recomputing it here races
        # the request across a second boundary, so validate the emailed
        # link itself instead.
        match = re.search(r"/claim/\?uid=(\S+)&token=(\S+)", mail.outbox[0].body)
        assert match is not None
        uid, token = match.groups()
        assert uid == urlsafe_base64_encode(force_bytes(member.pk))
        assert default_token_generator.check_token(member, token)

    def test_unknown_email_gets_same_response_no_mail(self):
        response = APIClient().post(RESET_URL, {"email": "nobody@example.com"})

        assert response.status_code == 200
        assert len(mail.outbox) == 0

    def test_unusable_password_still_gets_link(self):
        # Invited members have no password yet; the claim link is how
        # they set the first one.
        member = UserFactory(username="invited", email="invited@example.com")
        member.set_unusable_password()
        member.save()

        response = APIClient().post(RESET_URL, {"email": member.email})

        assert response.status_code == 200
        assert len(mail.outbox) == 1


class TestConfirmReset:
    def test_valid_token_sets_password(self):
        member = UserFactory(username="invited", email="invited@example.com")
        member.set_unusable_password()
        member.save()
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = default_token_generator.make_token(member)

        response = APIClient().post(
            CONFIRM_URL,
            {"uid": uid, "token": token, "new_password": "s3cure-pass!"},
        )

        assert response.status_code == 200
        member.refresh_from_db()
        assert member.has_usable_password()
        assert member.check_password("s3cure-pass!")

        tokens = APIClient().post(
            "/api/v1/auth/token/",
            {"username": member.username, "password": "s3cure-pass!"},
        )
        assert tokens.status_code == 200

    def test_bad_token_rejected_password_unchanged(self):
        member = UserFactory(username="invited", email="invited@example.com")
        member.set_password("old-pass!")
        member.save(update_fields=["password"])
        uid = urlsafe_base64_encode(force_bytes(member.pk))

        response = APIClient().post(
            CONFIRM_URL,
            {"uid": uid, "token": "bogus-token", "new_password": "s3cure-pass!"},
        )

        assert response.status_code == 400
        member.refresh_from_db()
        assert member.check_password("old-pass!")

    def test_weak_password_rejected(self):
        member = UserFactory(username="invited", email="invited@example.com")
        uid = urlsafe_base64_encode(force_bytes(member.pk))
        token = default_token_generator.make_token(member)

        response = APIClient().post(
            CONFIRM_URL, {"uid": uid, "token": token, "new_password": "123"}
        )

        assert response.status_code == 400
