from typing import ClassVar

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import OrgRole, Venue
from organizations.permissions import IsStaff, IsVenueMember
from organizations.serializers import MeSerializer


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
        from django.db.models import Q

        fragment = request.query_params.get("q", "")
        members = (
            OrgRole.objects.filter(
                Q(venue=request.venue)
                | Q(venue=None, organization=request.venue.organization),
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
