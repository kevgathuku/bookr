"""Staff back-office for partners (separate from the partner channel)."""

from typing import ClassVar

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from aggregators.models import Aggregator, AggregatorEventLog
from aggregators.tokens import new_token
from organizations.permissions import IsStaff, IsVenueMember


class StaffAggregatorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Aggregator
        fields: ClassVar[list[str]] = [
            "slug",
            "name",
            "seat_allotment",
            "cancel_cutoff_minutes",
            "commission_percent",
            "active",
            "webhook_url",
        ]


class AggregatorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AggregatorEventLog
        fields: ClassVar[list[str]] = [
            "id",
            "method",
            "path",
            "status_code",
            "created_at",
        ]


class StaffAggregatorListView(generics.ListCreateAPIView):
    """Partner-global: any venue staff may manage partners."""

    queryset = Aggregator.objects.order_by("slug")
    serializer_class = StaffAggregatorSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    @extend_schema(responses={201: StaffAggregatorSerializer})
    def post(self, request, *args, **kwargs):
        form = StaffAggregatorSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        raw, token_hash = new_token()
        # Machine account, never a booking member: no address to notify,
        # so blank email is intentional (notify fails loudly if ever used).
        service_user = get_user_model().objects.create_user(
            username=f"svc-{form.validated_data['slug']}"
        )
        partner = Aggregator.objects.create(
            **form.validated_data,
            api_token_hash=token_hash,
            service_user=service_user,
        )
        return Response(
            {**StaffAggregatorSerializer(partner).data, "api_token": raw},
            status=201,
        )


class StaffAggregatorDetailView(generics.RetrieveUpdateAPIView):
    queryset = Aggregator.objects.all()
    serializer_class = StaffAggregatorSerializer
    lookup_field = "slug"
    lookup_url_kwarg = "slug"
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    http_method_names: ClassVar[list[str]] = [  # type: ignore[misc]
        "get",
        "patch",
        "head",
        "options",
    ]


class StaffAggregatorRotateView(APIView):
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    @extend_schema(request=None, responses={200: StaffAggregatorSerializer})
    def post(self, request, slug):
        partner = get_object_or_404(Aggregator, slug=slug)
        raw, token_hash = new_token()
        partner.api_token_hash = token_hash
        partner.save(update_fields=["api_token_hash"])
        return Response({**StaffAggregatorSerializer(partner).data, "api_token": raw})


class StaffAggregatorEventsView(generics.ListAPIView):
    serializer_class = AggregatorEventSerializer
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    permission_classes: ClassVar[list] = [  # type: ignore[misc]
        IsVenueMember,
        IsStaff,
    ]

    def get_queryset(self):
        partner = get_object_or_404(Aggregator, slug=self.kwargs["slug"])
        return AggregatorEventLog.objects.filter(aggregator=partner)[:100]
