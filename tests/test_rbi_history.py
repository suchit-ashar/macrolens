from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from ingest import rbi_history


def make_table40(path, sheets):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        ws.append([None, "TABLE 40 : MAJOR MONETARY POLICY RATES ..."])
        ws.append([None, "(Per cent)"])
        ws.append([None, "Effective Date", "Bank Rate", "Fix Range LAF Rates", None, "SDF", "MSF", "CRR", "SLR"])
        ws.append([None, None, None, "Repo", "Reverse Repo"])
        ws.append([None, 1, 2, 3, 4, 5, 6, 7, 8])
        for d, repo, crr in rows:
            ws.append([None, d, "-", repo, "-", "-", "-", crr, "-"])
        ws.append([None, "Notes : 1. - : Indicates no change."])
    wb.save(path)
    return path


def test_parses_repo_column_across_sheets_and_skips_no_change(tmp_path):
    p = make_table40(tmp_path / "t40.xlsx", {
        "T_40(i)": [(datetime(2008, 4, 26), "-", 7.75), (datetime(2008, 6, 12), 8, "-")],
        "T_40(ii)": [(datetime(2025, 6, 6), 5.5, "-"), (datetime(2025, 12, 5), 5.25, "-")],
    })
    df = rbi_history.parse_table40(p)
    assert [d.strftime("%Y-%m-%d") for d in df["date"]] == ["2008-06-12", "2025-06-06", "2025-12-05"]
    assert list(df["value"]) == [8.0, 5.5, 5.25]


def test_no_repo_rows_raises(tmp_path):
    p = make_table40(tmp_path / "t40.xlsx", {"T": [(datetime(2008, 4, 26), "-", 7.75)]})
    with pytest.raises(rbi_history.Table40Error):
        rbi_history.parse_table40(p)


def test_rerun_keeps_daily_changes_and_drops_repeats():
    t40 = pd.DataFrame({"date": pd.to_datetime(["2025-06-06", "2025-12-05"]), "value": [5.5, 5.25]})
    stored = pd.DataFrame({"date": pd.to_datetime(["2025-12-05", "2026-10-07", "2026-11-21"]),
                           "value": [5.25, 5.5, 5.5]})
    h = rbi_history.build_history(t40, stored)
    assert [d.strftime("%Y-%m-%d") for d in h["date"]] == ["2025-06-06", "2025-12-05", "2026-10-07"]
    assert list(h["value"]) == [5.5, 5.25, 5.5]
