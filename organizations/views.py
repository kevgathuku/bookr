import logging
from typing import ClassVar

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrgRole, Venue
from organizations.permissions import IsStaff, IsVenueMember
from organizations.serializers import (
    MeSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetSerializer,
)

User = get_user_model()

logger = logging.getLogger(__name__)


class MeView(APIView):
    """Who am I: username + roles for the venue switcher."""

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        roles = (
            OrgRole.objects.filter(user=request.user)
            .select_related("organization", "venue")
            .order_by("organization__slug")
        )
        org_ids = {row.organization_id for row in roles}
        venues = (
            Venue.objects.filter(organization__in=org_ids)
            .select_related("organization")
            .order_by("slug")
        )
        return Response(
            {
                "id": request.user.pk,
                "username": request.user.username,
                "memberships": [
                    {
                        "organization": row.organization.slug,
                        "venue": row.venue.slug if row.venue else None,
                        "role": row.role,
                    }
                    for row in roles
                ],
                "venues": [
                    {
                        "organization": venue.organization.slug,
                        "slug": venue.slug,
                        "name": venue.name,
                        "time_zone": venue.time_zone,
                    }
                    for venue in venues
                ],
            }
        )


class MemberSearchSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()


def _send_claim_link(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = request.build_absolute_uri(f"/claim/?uid={uid}&token={token}")
    body = "Your studio created your Bookr account. Set your password here:\n"
    try:
        send_mail("Set up your Bookr account", body + link, None, [user.email])
    except Exception:
        logger.exception("claim link failed")


def _user_from_uid(uid):
    try:
        pk = int(force_str(urlsafe_base64_decode(uid)))
    except TypeError, ValueError, OverflowError:
        return None
    return User.objects.filter(pk=pk).first()


class PasswordResetView(APIView):
    """Invite-claim step 1: email a set-password link.

    Anonymous by necessity (the claimer has no credentials yet); the
    response never reveals whether the address belongs to a member.
    """

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [AllowAny]  # type: ignore[misc]

    @extend_schema(request=PasswordResetSerializer, responses={200: dict})
    def post(self, request):
        form = PasswordResetSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        members = User.objects.filter(
            email__iexact=form.validated_data["email"],
            is_active=True,
        )
        for member in members:
            _send_claim_link(request, member)
        return Response(
            {"detail": "If that address belongs to a member, a link is on its way."}
        )


class PasswordResetConfirmView(APIView):
    """Invite-claim step 2: a valid link sets the password."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [AllowAny]  # type: ignore[misc]

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: dict})
    def post(self, request):
        form = PasswordResetConfirmSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        member = _user_from_uid(form.validated_data["uid"])
        token = form.validated_data["token"]
        if member is None or not default_token_generator.check_token(member, token):
            raise ValidationError({"token": "This link is invalid or expired."})
        try:
            validate_password(form.validated_data["new_password"], member)
        except DjangoValidationError as error:
            raise ValidationError({"new_password": error.messages})
        member.set_password(form.validated_data["new_password"])
        member.save(update_fields=["password"])
        return Response({"detail": "Password set. You can log in now."})


class MemberSearchView(APIView):
    """Frontdesk finds venue members by username fragment."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    @extend_schema(
        responses=MemberSearchSerializer(many=True),
        parameters=[OpenApiParameter("q", str, required=False)],
    )
    def get(self, request):
        fragment = request.query_params.get("q", "")
        members = (
            OrgRole.objects.covering(request.venue)
            .filter(
                user__username__icontains=fragment,
            )
            .select_related("user")
            .order_by("user__username")[:20]
        )
        return Response(
            MemberSearchSerializer(
                [{"id": row.user.pk, "username": row.user.username} for row in members],
                many=True,
            ).data
        )
