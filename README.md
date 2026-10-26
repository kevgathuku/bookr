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

# 5. Run
uv run python manage.py runserver
```

## Testing

```bash
uv run pytest          # direnv supplies DATABASE_URL from .env; without it
                       # settings fail fast with KeyError (by design)
uv run pytest tests/test_organizations.py -q   # single file
```

Fresh start (destroys dev data): `docker compose down -v`, then repeat step 2. Data otherwise survives container recreations.
