from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from access.models import AccessPoint, hash_token


class ControllerAuthentication(BaseAuthentication):
    """Per-controller token: `Authorization: Token <secret>`."""

    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        scheme, _, plaintext = header.partition(" ")
        if scheme != "Token" or not plaintext:
            return None
        try:
            point = AccessPoint.objects.select_related("venue").get(
                api_token_hash=hash_token(plaintext)
            )
        except AccessPoint.DoesNotExist:
            raise AuthenticationFailed("Bad controller token.")
        return None, point

    def authenticate_header(self, request):
        return "Token"


class ControllerTokenScheme(OpenApiAuthenticationExtension):
    target_class = "access.auth.ControllerAuthentication"
    name = "ControllerToken"
    match_subclasses = True

    def get_security_definition(self, auto_schema):
        return {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "Token <controller-secret>",
        }
