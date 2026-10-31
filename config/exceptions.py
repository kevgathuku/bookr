"""DRF exception mapping for Django-native errors.

Service code raises django.core.exceptions.ValidationError for bad input;
DRF only maps its own APIException tree, so without this those surface
as 500s. One seam for the whole API.
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


def exception_handler(exc, context):
    if isinstance(exc, DjangoValidationError):
        messages = exc.messages
        detail = messages[0] if len(messages) == 1 else messages
        return Response({"detail": detail}, status=400)
    return drf_handler(exc, context)
