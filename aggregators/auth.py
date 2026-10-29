"""Per-partner token auth + throttle for the aggregator channel."""

from rest_framework import authentication, exceptions, throttling

from aggregators.models import Aggregator
from aggregators.tokens import verify

HEADER = "X-Partner-Token"


class AggregatorAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        raw = request.headers.get(HEADER)
        slug = (
            request.parser_context["kwargs"].get("slug")
            if request.parser_context
            else None
        )
        if not raw or not slug:
            return None
        try:
            partner = Aggregator.objects.select_related("service_user").get(
                slug=slug, active=True
            )
        except Aggregator.DoesNotExist:
            raise exceptions.AuthenticationFailed("Unknown partner.")
        if not verify(raw, partner.api_token_hash):
            raise exceptions.AuthenticationFailed("Bad partner token.")
        return partner.service_user, partner

    def authenticate_header(self, request):
        return HEADER


class AggregatorThrottle(throttling.SimpleRateThrottle):
    scope = "aggregator"
    rate = "100/min"

    def get_cache_key(self, request, view):
        partner = request.auth
        if partner is None:
            return None
        return self.cache_format % {"scope": self.scope, "ident": partner.pk}
