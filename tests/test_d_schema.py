"""db/schema.sql is the contract copy, db/migrate.sql is what runs. Keep them the same shape.

Nothing enforces that two hand-maintained SQL files describe the same database, and the way
this breaks is quiet: a column added to migrate.sql only, then a reviewer diffs schema.sql
against [C3] in TASK.md, sees no difference, and signs off on a database that has drifted.
"""

import re
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "db"
SCHEMA = (DB / "schema.sql").read_text(encoding="utf-8")
MIGRATE = (DB / "migrate.sql").read_text(encoding="utf-8")

CREATE = re.compile(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\(", re.I)
CONSTRAINTS = {"primary", "foreign", "unique", "check", "constraint"}


def tables(sql):
    """{table: [column, ...]} — a crude parser, but the files are ours and stay simple."""
    out = {}
    for m in CREATE.finditer(sql):
        depth, i = 1, m.end()
        while depth:                       # walk to the paren that closes the column list
            depth += {"(": 1, ")": -1}.get(sql[i], 0)
            i += 1
        body = re.sub(r"--[^\n]*", "", sql[m.end():i - 1])
        cols, segment, depth = [], "", 0
        for ch in body + ",":
            if ch == "," and depth == 0:
                token = segment.split()
                if token and token[0].lower() not in CONSTRAINTS:
                    cols.append(token[0].lower())
                segment = ""
                continue
            depth += {"(": 1, ")": -1}.get(ch, 0)
            segment += ch
        out[m.group(1).lower()] = cols
    return out


def test_same_tables():
    assert set(tables(SCHEMA)) == set(tables(MIGRATE))


def test_same_columns():
    schema, migrate = tables(SCHEMA), tables(MIGRATE)
    for name in schema:
        assert schema[name] == migrate[name], f"{name} differs between schema.sql and migrate.sql"


def test_every_contract_table_is_present():
    # [C3] names these ten; a missing one breaks a lane that is not ours.
    expected = {"departments", "users", "cameras", "sightings", "watchlist",
                "alerts", "alert_events", "access_grants", "audit_log"}
    assert expected <= set(tables(SCHEMA))


def test_hypertable_is_created_before_any_index():
    # Order matters: create_hypertable() wants an empty table, and the indexes are what make
    # people start querying (and inserting) against it.
    for sql in (SCHEMA, MIGRATE):
        assert sql.index("create_hypertable") < sql.index("ON sightings ")


def test_all_five_sighting_indexes_survive_in_migrate():
    for target in ("(plate_norm, pts_first DESC)", "(plate_canon, pts_first DESC)",
                   "(camera_id, pts_first DESC)", "gin (plate_norm gin_trgm_ops)",
                   "hnsw (reid_vec vector_cosine_ops)"):
        assert target in SCHEMA and target in MIGRATE, target


def test_migrate_is_rerunnable():
    # Every CREATE in migrate.sql must be guarded, or a second run is a wall of errors.
    for stmt in re.findall(r"CREATE (?:TABLE|INDEX)[^(]*", MIGRATE):
        assert "IF NOT EXISTS" in stmt.upper(), stmt.strip()
    assert "if_not_exists => TRUE" in MIGRATE
