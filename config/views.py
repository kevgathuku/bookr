from django.db import OperationalError, connection
from django.http import JsonResponse


def healthz(request):
    # Liveness for compose/orchestrators: 200 only if the database answers.
    # No auth, no venue scoping — load balancers can't log in.
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})
