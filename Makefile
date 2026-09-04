.PHONY: up down seed check run stop demo survey report

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

# The four processes the console needs, backgrounded, with their logs in ./logs.
# Separate terminals are better for a demo - a crash is then visible instead of buried - but this
# is the one-command version for a laptop that is only being checked.
run:
	@mkdir -p logs
	python -m uvicorn --factory services.api.main:factory --host 127.0.0.1 --port 8000 > logs/api.log 2>&1 &
	python scripts/console_serve.py --port 5173 > logs/console.log 2>&1 &
	python services/api/persister.py --duration 86400 > logs/persister.log 2>&1 &
	python services/api/matcher.py --duration 86400 > logs/matcher.log 2>&1 &
	@sleep 6
	@curl -sf localhost:8000/api/healthz && echo " api ok" || echo " API DID NOT START - see logs/api.log"
	@curl -sf -o /dev/null localhost:5173/ && echo "console ok  ->  http://127.0.0.1:5173/" || echo "CONSOLE DID NOT START - see logs/console.log"

stop:
	-pkill -f "services.api.main:factory" || true
	-pkill -f "console_serve.py" || true
	-pkill -f "services/api/persister.py" || true
	-pkill -f "services/api/matcher.py" || true

# Synthetic traffic through the real path: same stream, same persister, same matcher.
demo:
	python scripts/fake_sightings.py --rate 5 --duration 1800

# What the grid actually delivers, and whether its plates are readable.
survey:
	python scripts/grid_survey.py --probe --workers 4

# Regenerate docs/accuracy-report.md. Never edit that file by hand.
report:
	python scripts/accuracy_report.py
