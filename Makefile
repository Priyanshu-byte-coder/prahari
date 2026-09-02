.PHONY: up down seed check

up:
	docker compose -f infra/docker-compose.yml up -d
	docker compose -f infra/docker-compose.yml ps

down:
	docker compose -f infra/docker-compose.yml down

# schema + load cameras.seed.json + camera_geo.json (db/ is lane D, data/*.json is lane G)
seed:
	psql "$${POSTGRES_DSN:-postgresql://sentinel:sentinel@localhost:5432/sentinel}" -f db/schema.sql
	python scripts/load_registry.py

# pytest + the RBAC scope test
check:
	pytest
