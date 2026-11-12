from django.db import OperationalError, connection
from django.http import HttpResponse, JsonResponse


def healthz(request):
    # Liveness for compose/orchestrators: 200 only if the database answers.
    # No auth, no venue scoping — load balancers can't log in.
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


def spa(request):
    """Same-origin SPA fallback: every non-API route serves the Vite build."""
    from pathlib import Path

    from django.conf import settings
    from django.http import Http404

    index = Path(settings.WHITENOISE_ROOT) / "index.html"
    if not index.is_file():
        raise Http404("Frontend not built (npm run build in frontend/).")
    return HttpResponse(index.read_text(), content_type="text/html")
