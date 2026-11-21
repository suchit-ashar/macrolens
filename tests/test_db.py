import pandas as pd

from storage import db
from transform.normalize import to_long

REG = {
    "a": {"id": "a", "country": "IN", "name": "A", "source": "T", "source_series": "s", "unit": "percent",
          "frequency": "daily", "source_url": "https://example.org"},
    "b": {"id": "b", "country": "US", "name": "B", "source": "T", "source_series": "s", "unit": "index",
          "frequency": "monthly", "source_url": "https://example.org"},
}


def write(tmp_path, entry, dates, values, fetched_at):
    df = to_long(pd.DataFrame({"date": dates, "value": values}), entry, fetched_at=fetched_at)
    path = tmp_path / f"{entry['id']}.parquet"
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
    df.to_parquet(path, index=False)


def test_latest_view_and_summary(tmp_path):
    write(tmp_path, REG["a"], ["2026-11-19", "2026-11-20"], [7.0, 7.1], "2026-11-20T00:00:00")
    write(tmp_path, REG["a"], ["2026-11-20"], [7.2], "2026-11-21T00:00:00")  # revision
    con = db.build(":memory:", clean_dir=tmp_path, registry=REG)

    assert con.execute("SELECT count(*) FROM observations").fetchone()[0] == 3
    assert list(db.series(con, "a")["value"]) == [7.0, 7.2]
    assert len(db.vintages(con, "a")) == 3

    s = con.execute("SELECT indicator_id, value, prev_value FROM summary ORDER BY indicator_id").fetchall()
    assert s[0] == ("a", 7.2, 7.0)
    assert s[1][0] == "b" and s[1][1] is None  # registered but no data yet


def test_build_with_no_files(tmp_path):
    con = db.build(":memory:", clean_dir=tmp_path, registry=REG)
    assert con.execute("SELECT count(*) FROM summary").fetchone()[0] == 2
