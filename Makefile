.PHONY: up down seed check run stop status demo survey report

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

# The four processes the console needs. The work is in scripts/run_stack.py rather than here,
# because `make` is not present on every machine this has to run on - including the laptop the
# demo video is recorded from - and the Python version is the one that gets tested.
run:
	python scripts/run_stack.py start

stop:
	python scripts/run_stack.py stop

status:
	python scripts/run_stack.py status

# Synthetic traffic through the real path: same stream, same persister, same matcher.
demo:
	python scripts/fake_sightings.py --rate 5 --duration 1800

# What the grid actually delivers, and whether its plates are readable.
survey:
	python scripts/grid_survey.py --probe --workers 4

# Regenerate docs/accuracy-report.md. Never edit that file by hand.
report:
	python scripts/accuracy_report.py
