"""Partner channel: idempotent allotment-capped booking + contract cancel."""

from typing import ClassVar

from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from aggregators.auth import AggregatorAuthentication, AggregatorThrottle
from aggregators.models import Aggregator, AggregatorBooking, AggregatorEventLog
from aggregators.serializers import PartnerSessionSerializer
from aggregators.services import book_partner_seat, cancel_partner_booking
from aggregators.webhooks import send_webhook
from booking.http import mapped_errors
from booking.serializers import BookingSerializer
from scheduling.catalogue import ClassSession
from scheduling.views import MAX_WINDOW, parse_window_bound


class PartnerBookSerializer(serializers.Serializer):
    session = serializers.PrimaryKeyRelatedField(queryset=ClassSession.objects.all())
    external_id = serializers.CharField(max_length=128)


def _log(partner, request, status_code):
    AggregatorEventLog.objects.create(
        aggregator=partner,
        method=request.method,
        path=request.path,
        status_code=status_code,
    )


def _partner(request) -> Aggregator:
    partner = request.auth
    if not isinstance(partner, Aggregator):
        raise NotFound("Unknown partner.")
    return partner


class PartnerBookingsView(APIView):
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    authentication_classes: ClassVar[list] = [  # type: ignore[misc]
        AggregatorAuthentication,
    ]
    throttle_classes: ClassVar[list] = [AggregatorThrottle]  # type: ignore[misc]

    @extend_schema(request=PartnerBookSerializer, responses=BookingSerializer)
    def post(self, request, slug):
        partner = _partner(request)
        form = PartnerBookSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        with mapped_errors():
            booking, created = book_partner_seat(
                partner, data["session"], data["external_id"]
            )
        _log(partner, request, 201 if created else 200)
        if created and partner.webhook_url:
            send_webhook.delay(
                partner.webhook_url,
                partner.webhook_secret,
                "booking.created",
                {"external_id": data["external_id"], "booking": booking.pk},
            )
        return Response(
            BookingSerializer(booking).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PartnerCancelView(APIView):
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    authentication_classes: ClassVar[list] = [  # type: ignore[misc]
        AggregatorAuthentication,
    ]
    throttle_classes: ClassVar[list] = [AggregatorThrottle]  # type: ignore[misc]

    @extend_schema(request=None, responses=BookingSerializer)
    def post(self, request, slug, external_id):
        partner = _partner(request)
        link = (
            AggregatorBooking.objects.select_related("booking", "booking__session")
            .filter(aggregator=partner, external_id=external_id)
            .first()
        )
        if link is None:
            _log(partner, request, 404)
            raise NotFound("No such booking.")
        with mapped_errors():
            booking = cancel_partner_booking(partner, link.booking)
        _log(partner, request, 200)
        if partner.webhook_url:
            send_webhook.delay(
                partner.webhook_url,
                partner.webhook_secret,
                "booking.cancelled",
                {"external_id": external_id, "status": booking.status},
            )
        return Response(BookingSerializer(booking).data)


class PartnerScheduleView(APIView):
    # ClassVar is runtime-truth; DRF stubs declare these as instance vars.
    authentication_classes: ClassVar[list] = [  # type: ignore[misc]
        AggregatorAuthentication,
    ]
    throttle_classes: ClassVar[list] = [AggregatorThrottle]  # type: ignore[misc]

    @extend_schema(
        responses=PartnerSessionSerializer(many=True),
        parameters=[
            OpenApiParameter("from", str, required=False),
            OpenApiParameter("to", str, required=False),
        ],
    )
    def get(self, request, slug):
        partner = _partner(request)
        params = request.query_params
        start = parse_window_bound(params.get("from"), timezone.now())
        end = parse_window_bound(params.get("to"), start + MAX_WINDOW)
        if end <= start or end - start > MAX_WINDOW:
            raise ValidationError("Window must be within 31 days.")
        sessions = (
            ClassSession.objects.live()
            .in_window(start, end)
            .select_related("offering", "offering__teacher")
            .order_by("starts_at")[:200]
        )
        _log(partner, request, 200)
        return Response(PartnerSessionSerializer(sessions, many=True).data)
