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

**downtown-dance** (org-wide roles; venues Main Studio + Annex,
America/New_York; Annex stays session-free for the venue switcher):

| User | Role | Try |
| --- | --- | --- |
| `demo-owner` | owner | Manage UI: partner aggregators |
| `demo-manager` | manager | Manage UI, staff APIs |
| `demo-teacher` | teacher | Teach: own sessions |
| `demo-frontdesk` | frontdesk | Desk: roster, check-in, adjustments |
| `demo-member` | member | booked Spin, 9 credits left |
| `demo-member2` | member | booked Spin, 9 credits left |

Schedule: Spin Mon/Wed/Fri 07:00 + Yoga Tue/Thu 18:00 (Main).
Plan: Dance 10-Class Pack, 10 credits issued to both members.

**uptown-box** (per-venue: each membership pins exactly one venue;
venues The Box + Annex Box, America/Chicago):

| User | Role | Try |
| --- | --- | --- |
| `demo-pinned` | member → The Box | booked Box class, Box 5-Class Pack |
| `demo-coach` | teacher → Annex Box | Teach scoped to one venue |

Cross-org checks: `demo-member` sees nothing in uptown-box and vice
versa (tenancy answers 404).

`--e2e` adds the fixed `e2e-run` org (venues Main + Annex, Africa/Nairobi):

| User | Role | Notes |
| --- | --- | --- |
| `e2e-run-member` | member (org-wide) | 10-credit membership |
| `e2e-run-booker` | member (org-wide) | holds a Spin booking |
| `e2e-run-stranger` | member (org-wide) | spare member, no bookings |
| `e2e-run-teacher` | teacher (org-wide) | teaches Main Spin + Annex Yoga |
| `e2e-run-frontdesk` | frontdesk (org-wide) | desk check-in / adjustments |

Owner and manager are seeded (`demo-owner`, `demo-manager`), so the
Manage UI works out of the box. Staff screens beyond that live in the
Django admin (class/offering, plan, and policy authoring). API
permissions are role-based (no superuser bypass), so a bare superuser
still 404s — give it an org-wide owner role instead:

```bash
uv run python manage.py createsuperuser
uv run python manage.py shell -c "
from django.contrib.auth import get_user_model
from organizations.models import Organization, OrgRole
user = get_user_model().objects.get(username='<pick a username>')
org = Organization.objects.get(slug='downtown-dance')
OrgRole.objects.get_or_create(
    organization=org, venue=None, user=user,
    defaults={'role': OrgRole.Role.OWNER},
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

**C. Compose rehearsal (prod image + services):** the dress-rehearsal
deploy — web (migrates on boot), worker, beat, Flower, mailpit, all on
the `db` + `redis` services.

```bash
docker compose up -d --build   # first run builds the prod image
docker compose ps              # all services Up (db + redis healthy)
```

| Service | Address | Notes |
| --- | --- | --- |
| web | http://localhost:8000 | prod settings, `/healthz` |
| Flower | http://localhost:5555 | basic-auth, see `FLOWER_BASIC_AUTH` |
| mailpit | http://localhost:8026 | member notices land here |

Flower and mailpit bind localhost only and Flower needs its
credentials (`staff:rehearsal-only` unless overridden) — staff-only
like the admin; prod fronts them with the same proxy/auth. Worker
owns `promote_waitlist`/`sweep_expired_holds` off the eager path;
beat fires the sweep every 15 minutes; both are visible in Flower.
Tear the rehearsal down with `docker compose stop web worker beat
flower mailpit redis` (leave `db` running for tests).


## Testing

```bash
uv run pytest -q -n auto -m "not e2e and not smoke"  # unit suite, parallel
uv run pytest tests/e2e -q -m "smoke"                # live-server API smoke, serial
uv run pytest tests/e2e -q -m "e2e"                  # Playwright browser suite, serial
uv run pytest organizations/tests/test_organizations.py -q   # single file
```

The browser suite needs the built SPA (`pnpm --dir frontend run build`,
served same-origin) and browser binaries (`uv run playwright install
chromium`) — CI installs both; the unit suite needs neither.

Quality gates (all must pass; CI runs the same):

```bash
uv run ruff check . && uv run ruff format --check .
DATABASE_URL=postgres://bookr:bookr@localhost:5433/bookr_test \
  SECRET_KEY=ci-only-insecure-key uv run mypy .
uv run flake8 <touched files>   # wemake-python-styleguide, see .flake8
cd frontend && pnpm run lint && pnpm run typecheck && pnpm run test
```

```bash
uv run pytest          # direnv supplies DATABASE_URL from .env; without it
                       # settings fail fast with KeyError (by design)
```

Test DB: Django creates a `test_*` database per run and destroys it after —
dev data is never touched. `pyproject.toml` sets `--reuse-db`, so `test_bookr`
(or `test_bookr_test` under the default settings) persists between runs for
speed and inspection (`docker compose exec db psql -U bookr -d test_bookr`).
After a migration change, rebuild it once with `uv run pytest --create-db`.
An exported `DATABASE_URL` wins over the test-settings default (`setdefault`
never clobbers), so check your shell env if the wrong DB gets templated.

Fresh start (destroys dev data): `docker compose down -v`, then repeat step 2. Data otherwise survives container recreations.
