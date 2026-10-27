from typing import ClassVar

from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from organizations.models import Membership, Venue, VenuePolicy
from organizations.permissions import IsStaff, IsVenueMember
from organizations.serializers import MeSerializer


class VenuePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = VenuePolicy
        fields: ClassVar[list[str]] = [
            "id",
            "venue",
            "valid_from",
            "valid_until",
            "class_late_cancel_hours",
            "appointment_late_cancel_hours",
            "forfeit_late_cancel",
            "waitlist_hold_minutes",
            "booking_buffer_minutes",
        ]


class PolicyListView(generics.ListAPIView):
    """Version history, newest first. Staff only; versions never edit."""

    serializer_class = VenuePolicySerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    def get_queryset(self):
        return VenuePolicy.objects.filter(venue=self.request.venue).order_by(
            "-valid_from"
        )


class ActivateSerializer(serializers.Serializer):
    class_late_cancel_hours = serializers.IntegerField(required=False)
    appointment_late_cancel_hours = serializers.IntegerField(required=False)
    forfeit_late_cancel = serializers.BooleanField(required=False)
    waitlist_hold_minutes = serializers.IntegerField(required=False)
    booking_buffer_minutes = serializers.IntegerField(required=False)


class PolicyActivateView(APIView):
    """Retire the open version + insert the successor, atomically."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    @extend_schema(request=ActivateSerializer, responses=VenuePolicySerializer)
    def post(self, request):
        form = ActivateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        policy = VenuePolicy.objects.activate(request.venue, **form.validated_data)
        return Response(VenuePolicySerializer(policy).data, status=201)


class MeView(APIView):
    """Who am I: username + memberships for the venue switcher."""

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        memberships = (
            Membership.objects.filter(user=request.user)
            .select_related("organization", "venue")
            .order_by("organization__slug")
        )
        org_ids = {mem.organization_id for mem in memberships}
        venues = (
            Venue.objects.filter(organization__in=org_ids)
            .select_related("organization")
            .order_by("slug")
        )
        return Response(
            {
                "username": request.user.username,
                "memberships": [
                    {
                        "organization": mem.organization.slug,
                        "venue": mem.venue.slug if mem.venue else None,
                        "role": mem.role,
                    }
                    for mem in memberships
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


class CurrentPolicyView(APIView):
    """Open policy windows for countdown display."""

    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
    ]

    @extend_schema(responses=VenuePolicySerializer)
    def get(self, request):
        policy = (
            VenuePolicy.objects.filter(venue=request.venue, valid_until__isnull=True)
            .order_by("-valid_from")
            .first()
        )
        if policy is None:
            raise NotFound("No such venue.")
        return Response(VenuePolicySerializer(policy).data)


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
        fragment = request.query_params.get("q", "")
        members = (
            Membership.objects.filter(
                Q(venue=request.venue)
                | Q(venue=None, organization=request.venue.organization),
                user__username__icontains=fragment,
            )
            .select_related("user")
            .order_by("user__username")[:20]
        )
        return Response(
            MemberSearchSerializer(
                [
                    {"id": membership.user.pk, "username": membership.user.username}
                    for membership in members
                ],
                many=True,
            ).data
        )
