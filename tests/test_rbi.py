import pytest

from ingest import rbi

HTML = """<div class="policy"><h3>Policy&nbsp; Rates</h3>
<table><tr><td>Policy Repo Rate</td><td>: 5.50%</td></tr>
<tr><td>Standing Deposit Facility Rate</td><td>: 5.25%</td></tr>
<tr><td>Fixed Reverse Repo Rate</td><td>: 3.35%</td></tr></table></div>"""


def test_parses_repo_rate_not_reverse_repo():
    assert rbi.parse_rate(HTML, "Policy Repo Rate") == 5.50
    assert rbi.parse_rate(HTML, "Fixed Reverse Repo Rate") == 3.35


def test_missing_label_raises():
    with pytest.raises(rbi.RbiError, match="not found"):
        rbi.parse_rate("<p>maintenance</p>", "Policy Repo Rate")


def test_implausible_value_raises():
    with pytest.raises(rbi.RbiError, match="looks wrong"):
        rbi.parse_rate("Policy Repo Rate : 55.0%", "Policy Repo Rate")
