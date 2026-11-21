from datetime import date

import pandas as pd
import pytest

from ingest import imf

BODY = {"data": {
    "dataSets": [{"series": {"0:0:0": {"observations": {
        "0": ["84.80"], "1": ["84.26"], "2": ["83.08"], "3": ["81.27"]}}}}],
    "structures": [{"dimensions": {"observation": [{"values": [
        {"value": "2024"}, {"value": "2025"}, {"value": "2026"}, {"value": "2027"}]}]}}],
}}


class Resp:
    status_code = 200

    def __init__(self, payload):
        self._p, self.text = payload, str(payload)

    def json(self):
        return self._p


class FakeSession:
    def __init__(self):
        self.headers = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.headers.append(headers)
        return Resp(BODY)


def test_history_and_projection_are_split_at_current_year():
    s = FakeSession()
    hist, _ = imf.fetch("WEO:IND.GGXWDG_NGDP.A", session=s, save_raw=False, today=date(2026, 11, 21))
    proj, _ = imf.fetch("WEO:IND.GGXWDG_NGDP.A:proj", session=s, save_raw=False, today=date(2026, 11, 21))
    assert [d.year for d in hist["date"]] == [2024, 2025]
    assert [d.year for d in proj["date"]] == [2026, 2027]
    assert hist["value"].iloc[-1] == pytest.approx(84.26)
    assert "sdmx.data+json" in s.headers[0]["Accept"]


def test_bad_layout_raises():
    with pytest.raises(imf.ImfError):
        imf.parse_sdmx({"data": {}})


def test_bad_source_series():
    with pytest.raises(imf.ImfError):
        imf.fetch("WEO")
