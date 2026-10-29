# Rollback runbook (prod compose)

## Roll forward is the default
Deploy = build a new tag, `up -d`, migrate one-off. Rollback only when the
new image is broken and the fix can't go forward in minutes.

## Roll back the image (code only, no migration involved)
1. `docker compose -f docker-compose.prod.yml up -d` with the previous tag:
   `TAG=2026-10-26 docker compose ...` (set `image: bookr:${TAG:-latest}`
   or retag: `docker tag bookr:2026-10-26 bookr:latest` then `up -d`).
2. Watch `logs web worker beat`; hit `/healthz`.

## Roll back a migration (schema changed)
Django migrates backwards per app — plan BEFORE deploying:
1. Note the migration names in the release (`showmigrations`).
2. To revert: `run --rm web python manage.py migrate <app> <previous>` per
   app, in reverse dependency order (aggregators → access → passes →
   booking → scheduling → organizations), then redeploy the previous image.
3. Data-destroying migrations (none so far — all additive) need a backup
   first: `docker compose exec db pg_dump -U bookr bookr > backup.sql`.

## Nuclear option (staging only, never prod)
`docker compose -f docker-compose.prod.yml down -v` destroys everything;
`up -d` + migrate + `seed_demo --e2e-only` rebuilds it. Verified green —
this is the dress-rehearsal proof, not a prod procedure.
