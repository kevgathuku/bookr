.PHONY: test test-all test-smoke test-e2e test-fresh lint seed seed-e2e migrate help

PYTEST := uv run pytest -q

# Fast unit + API suite (default): parallel, skips live-server smoke/e2e.
test:
	$(PYTEST) -n auto -m "not e2e and not smoke"

# Full suite, serial (smoke/e2e need a live server: no xdist).
test-all:
	$(PYTEST)

# Per-commit live-server smoke only (serial).
test-smoke:
	$(PYTEST) -m smoke

# Full nightly/pre-release e2e (serial; needs worker, mailpit, frontend).
test-e2e:
	$(PYTEST) -m e2e

# Same as test, but rebuilds test DBs (required after editing a migration).
test-fresh:
	$(PYTEST) -n auto -m "not e2e and not smoke" --create-db

lint:
	uv run ruff check .
	uv run ruff format --check .

# Seed demo orgs (re-runnable): one spanning + one per-venue.
seed:
	uv run python manage.py seed_demo

# Seed only the fixed e2e-run org (known users, short windows).
seed-e2e:
	uv run python manage.py seed_e2e

migrate:
	uv run python manage.py migrate

help:
	@echo "test        unit+API, parallel, skips smoke/e2e (default)"
	@echo "test-all    everything, serial"
	@echo "test-smoke  live-server smoke only"
	@echo "test-e2e    full e2e (needs worker, mailpit, frontend)"
	@echo "test-fresh  like test, rebuilds test DBs (after migration edits)"
	@echo "lint        ruff check + format check"
	@echo "seed        demo orgs (re-runnable)"
	@echo "seed-e2e    fixed e2e-run org only"
	@echo "migrate     apply migrations"
