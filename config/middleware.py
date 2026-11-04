from organizations.tenancy import VENUE_HEADER, resolve_venue


class VenueMiddleware:
    """Resolve request.venue / request.organization once per request.

    Only sees session-authenticated users — DRF token/JWT auth runs later, so
    permissions lazily resolve via tenancy.ensure_venue for the rest. Header
    wins; without it, fall back to the user's pinned staff role first.
    Roles are stashed on the request so permissions add no queries.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.venue = None
        request.organization = None
        request.org_roles = []
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            resolved = resolve_venue(user, request.headers.get(VENUE_HEADER))
            request.venue = resolved.venue
            request.organization = resolved.organization
            request.org_roles = resolved.org_roles
        return self.get_response(request)
