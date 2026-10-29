# Bookr — multi-tenant venue management (classes, bookings, credit passes, aggregators, door access)

Contract in `SPEC.md`; build path in `TUTORIAL.md` ( lessons in `lessons/`, start at `0001`).

## Setup

Prereqs: [uv](https://docs.astral.sh/uv/), Docker, and optionally direnv. Python 3.14 comes via `uv`.

```bash
# 1. Dependencies
uv sync

# 2. Database (custom image: stock Postgres 18 + btree_gist, needed for
#    the no-double-booking constraints in lesson 3).
#    Port 5433: Homebrew Postgres already owns localhost:5432 on dev machines.
docker compose up -d db

# 3. Environment (settings read strictly from env — a missing DATABASE_URL
#    fails at import, by design)
cp .env.example .env
uv run python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
# → paste the output as SECRET_KEY in .env
direnv allow   # or: export $(cat .env | xargs) per shell

# 4. Migrate + verify
uv run python manage.py migrate
uv run python manage.py check
docker compose exec db psql -U bookr -d bookr -c "\dx"   # expect btree_gist

# 5. Run (API only)
uv run python manage.py runserver
```

## Running the full app (backend + frontend)

Two ways; both need the API on :8000. Seed demo data first — the command
prints the usernames it created (password is `password` for every seed user):

```bash
uv run python manage.py seed_demo        # faker demo orgs (names printed)
uv run python manage.py seed_demo --e2e  # also the fixed e2e-run org
                                         # (e2e-run-member / password)
```

### Seeded users (password is `password` for all of them)

`seed_demo` builds two orgs with different configs, eight fixed logins,
a week of classes, passes, and bookings — no manual setup before clicking
through. Re-runnable (exact-start classes never duplicate).

**downtown-dance** (spanning: one membership covers every venue;
venues Main Studio + Annex, America/New_York):

| User | Role | Try |
| --- | --- | --- |
| `demo-owner` | owner | Manage UI: policies, products, staff |
| `demo-manager` | manager | Manage UI, staff APIs |
| `demo-teacher` | teacher | Teach: own schedule, substitutions |
| `demo-frontdesk` | frontdesk | Desk: roster, check-in, adjustments |
| `demo-member` | member | booked Spin, 9 credits left |
| `demo-member2` | member | holds the capacity-1 Tiny seat (full) |

Schedule: Spin Mon/Wed/Fri 07:00 + Yoga Tue/Thu 18:00 (Main),
Tiny tomorrow (Annex Closet, capacity 1 — join the waitlist as
`demo-member`). Passes: Dance 10-Class Pack issued to both members.

**uptown-box** (per-venue: each membership pins exactly one venue;
venues The Box + Annex Box, America/Chicago):

| User | Role | Try |
| --- | --- | --- |
| `demo-pinned` | member → The Box | booked Box class, 5-Class Pack |
| `demo-coach` | teacher → Annex Box | Teach scoped to one venue |

Cross-org checks: `demo-member` sees nothing in uptown-box and vice
versa (tenancy answers 404).

`--e2e` adds the fixed `e2e-run` org (venues Main + Annex, Africa/Nairobi):

| User | Role | Notes |
| --- | --- | --- |
| `e2e-run-member` | member (spanning) | has a pass (10 credits) |
| `e2e-run-booker` | member (spanning) | holds a Spin booking |
| `e2e-run-stranger` | member (spanning) | spare member, no bookings |
| `e2e-run-teacher` | teacher | owns the schedule + appointments |
| `e2e-run-sub` | teacher | substitution cover |
| `e2e-run-frontdesk` | frontdesk | desk check-in / adjustments |

No owner or manager is seeded anywhere, so the Manage UI (manager+) has
no login yet. API permissions are membership-based (no superuser bypass),
so a superuser alone still 404s — attach an owner membership after creating
one (shell values match the demo org above; swap the slug for another org
to manage that one instead):

```bash
uv run python manage.py createsuperuser
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
from organizations.models import Membership, Organization
user = get_user_model().objects.get(username='<pick a username>')
org = Organization.objects.get(slug='downtown-dance')
Membership.objects.get_or_create(
    organization=org, venue=None, user=user, defaults={'role': 'owner'},
)"
```

**A. Dev mode (hot reload):** run the API and Vite side by side — Vite
proxies `/api` to :8000, so no CORS setup.

```bash
uv run python manage.py runserver        # terminal 1: API on :8000
cd frontend && pnpm install && pnpm dev # terminal 2: SPA on :5173
```

Open http://localhost:5173 and log in with a seeded user.

**B. Built SPA, same origin:** WhiteNoise serves `frontend/dist` from the
Django server itself (this is also how the e2e harness runs it). Rebuild
after any frontend change.

```bash
cd frontend && pnpm install && pnpm build
cd .. && uv run python manage.py runserver
```

Open http://localhost:8000 and log in. Health check for either mode:
`curl localhost:8000/healthz`.


## Testing

```bash
uv run pytest          # direnv supplies DATABASE_URL from .env; without it
                       # settings fail fast with KeyError (by design)
uv run pytest tests/test_organizations.py -q   # single file
```

Fresh start (destroys dev data): `docker compose down -v`, then repeat step 2. Data otherwise survives container recreations.
