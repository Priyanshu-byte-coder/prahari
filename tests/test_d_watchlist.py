"""D3's verify: a CSV with two bad rows reports both and writes nothing.

Partial imports are the failure that matters here. An operator who uploads 200 plates and is
told "12 failed" will fix 12 rows and re-upload; an operator who is told nothing, and whose
188 good rows went in, has a watchlist that silently disagrees with their spreadsheet.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api"))

from feeds import CSVFeed, EGujCopFeed, ManualFeed, VahanFeed, WatchlistFeed, pull_all  # noqa: E402
from store import Store                                                      # noqa: E402
from watchlist import ImportRejected, WatchlistRepo, validate_row            # noqa: E402

DSN = os.environ.get("TEST_POSTGRES_DSN",
                     os.environ.get("POSTGRES_DSN",
                                    "postgresql://sentinel:sentinel@localhost:5432/sentinel"))

GOOD = ("kind,plate,description,category,reason,severity\n"
        "plate,GJ01AB1234,,stolen vehicle,FIR 0123/2026,HIGH\n"
        "plate,GJ18CD5678,,blacklisted vehicle,repeat offender,MEDIUM\n")

TWO_BAD = ("kind,plate,description,category,reason,severity\n"
           "plate,GJ01AB1234,,stolen vehicle,FIR 0123/2026,HIGH\n"
           "plate,GJ01AB123,,stolen vehicle,FIR 0124/2026,HIGH\n"          # line 3: short plate
           "plate,GJ18CD5678,,car theft,FIR 0125/2026,HIGH\n"              # line 4: bad category
           "plate,GJ22EF9012,,suspect,FIR 0126/2026,LOW\n")


@pytest.fixture
def repo():
    store = Store(dsn=DSN)
    try:
        with store.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM watchlist LIMIT 1")
    except Exception as exc:
        pytest.skip(f"needs a migrated Postgres: {exc}")
    tag = f"test-{uuid.uuid4().hex[:8]}"
    yield WatchlistRepo(store), tag
    with store.conn as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM watchlist WHERE reason LIKE %s OR source = %s",
                    (f"%{tag}%", tag))
        cur.execute("DELETE FROM watchlist WHERE reason LIKE 'FIR 012%%/2026'")
    store.close()


def count(repo_obj):
    return len(repo_obj.list())


def test_two_bad_rows_are_both_reported_and_nothing_is_written(repo):
    repo_obj, _ = repo
    before = count(repo_obj)
    with pytest.raises(ImportRejected) as caught:
        repo_obj.import_csv(TWO_BAD)
    errors = caught.value.errors
    assert [e["line"] for e in errors] == [3, 4]
    assert "GJ01AB123" in errors[0]["reason"]
    assert "category" in errors[1]["reason"]
    assert count(repo_obj) == before          # the two good rows in that file did not land


def test_a_clean_csv_imports(repo):
    repo_obj, _ = repo
    before = count(repo_obj)
    assert repo_obj.import_csv(GOOD)["added"] == 2
    assert count(repo_obj) == before + 2


def test_missing_header_column_is_one_error_not_one_per_row(repo):
    repo_obj, _ = repo
    with pytest.raises(ImportRejected) as caught:
        repo_obj.import_csv("kind,plate,category,reason\nplate,GJ01AB1234,stolen vehicle,x\n")
    assert len(caught.value.errors) == 1
    assert caught.value.errors[0]["line"] == 1
    assert "description" in caught.value.errors[0]["reason"]
    assert "severity" in caught.value.errors[0]["reason"]


def test_validity_window_filters_the_list(repo):
    repo_obj, tag = repo
    now = datetime.now(timezone.utc)
    entry = validate_row({"kind": "plate", "plate": "GJ99ZZ0001", "category": "stolen vehicle",
                          "reason": f"expired {tag}", "severity": "LOW",
                          "valid_from": (now - timedelta(days=2)).isoformat(),
                          "valid_until": (now - timedelta(days=1)).isoformat()})
    entry.source = tag
    repo_obj.add(entry)
    active_ids = [e["id"] for e in repo_obj.list(active_at=now)]
    all_ids = [e["id"] for e in repo_obj.list()]
    assert set(all_ids) - set(active_ids)     # the expired entry is in one list and not the other


def test_plate_is_normalised_and_canonicalised_on_the_way_in():
    entry = validate_row({"kind": "plate", "plate": "ind gj 01-ab.1234",
                          "category": "stolen vehicle", "reason": "x", "severity": "HIGH"})
    assert entry.plate_norm == "GJ01AB1234"
    assert entry.plate_canon == "6J01A81234"


def test_person_entry_needs_a_description_not_a_plate():
    with pytest.raises(ValueError, match="no description"):
        validate_row({"kind": "description", "category": "suspect",
                      "reason": "x", "severity": "LOW"})


def test_feeds_satisfy_the_c6_protocol():
    assert isinstance(VahanFeed(), WatchlistFeed)
    assert isinstance(EGujCopFeed(), WatchlistFeed)
    assert isinstance(CSVFeed("nowhere.csv"), WatchlistFeed)


def test_stub_feeds_label_every_row_they_return():
    # A stub row must never be indistinguishable from a live one in a demo.
    for feed in (VahanFeed(), EGujCopFeed()):
        rows = feed.pull()
        assert rows and all(r.source.startswith("STUB:") for r in rows)
        assert feed.is_stub is True
        assert feed.request_shape and feed.response_shape


def test_csv_feed_skips_a_bad_line_instead_of_dying(tmp_path, caplog):
    # Opposite policy to the API import on purpose: a scheduled feed that raises stops
    # delivering every other row, and nobody finds out until an alert does not fire.
    path = tmp_path / "drop.csv"
    path.write_text(TWO_BAD, encoding="utf-8")
    entries = CSVFeed(path).pull()
    assert len(entries) == 2
    assert all(e.source == "csv" for e in entries)


def test_pull_all_survives_one_feed_being_down():
    class Broken:
        name = "broken"

        def pull(self, since):
            raise ConnectionError("refused")

    entries, failures = pull_all([Broken(), VahanFeed()])
    assert entries and failures == [("broken", "refused")]


def test_manual_feed_reads_from_the_repository(repo):
    repo_obj, tag = repo
    entry = validate_row({"kind": "plate", "plate": "GJ33MM4444", "category": "suspect",
                          "reason": f"manual {tag}", "severity": "LOW"})
    repo_obj.add(entry)
    reasons = [e["reason"] for e in ManualFeed(repo_obj).pull(datetime.now(timezone.utc))]
    assert f"manual {tag}" in reasons
