import pytest
from ingest.registry import load_registry, RegistryError


def test_real_registry_loads():
    reg = load_registry()
    assert "us_policy_rate" in reg and "in_repo_rate" in reg


def test_missing_field_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- id: x\n  country: US\n")
    with pytest.raises(RegistryError, match="missing"):
        load_registry(bad)


def test_duplicate_id_raises(tmp_path):
    entry = ("- id: a\n  country: US\n  name: n\n  source: FRED\n  source_series: S\n"
             "  unit: percent\n  frequency: daily\n  source_url: https://x.org\n")
    dup = tmp_path / "dup.yaml"
    dup.write_text(entry * 2)
    with pytest.raises(RegistryError, match="Duplicate"):
        load_registry(dup)
