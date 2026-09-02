.PHONY: up down seed check

up:
	docker compose -f infra/docker-compose.yml up -d
	docker compose -f infra/docker-compose.yml ps

down:
	docker compose -f infra/docker-compose.yml down

# schema + load cameras.seed.json + camera_geo.json (db/ is lane D, data/*.json is lane G)
# db/migrate.sql, not db/schema.sql: schema.sql is the verbatim copy of contract [C3] kept for
# diffing, so it has no IF NOT EXISTS guards, no compression or retention policies and no RLS.
# Running it twice fails; running migrate.sql twice is the point of it.
seed:
	psql "$${POSTGRES_DSN:-postgresql://sentinel:sentinel@localhost:5432/sentinel}" -v ON_ERROR_STOP=1 -f db/migrate.sql
	python scripts/load_registry.py

# pytest + the RBAC scope test
check:
	pytest
