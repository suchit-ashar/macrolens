"""Load and validate config/indicators.yaml."""
from pathlib import Path
import yaml

REQUIRED = ["id", "country", "name", "source", "source_series", "unit", "frequency", "source_url"]
FREQUENCIES = {"daily", "weekly", "fortnightly", "monthly", "quarterly", "annual", "event"}
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config" / "indicators.yaml"


class RegistryError(ValueError):
    pass


def load_registry(path: Path = DEFAULT_PATH) -> dict:
    """Return {indicator_id: entry}. Raises RegistryError with a clear message on bad entries."""
    entries = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or []
    registry = {}
    for i, entry in enumerate(entries):
        missing = [k for k in REQUIRED if not entry.get(k)]
        if missing:
            raise RegistryError(f"Entry #{i} ({entry.get('id', '?')}) missing: {', '.join(missing)}")
        if entry["frequency"] not in FREQUENCIES:
            raise RegistryError(f"{entry['id']}: unknown frequency '{entry['frequency']}'")
        if not str(entry["source_url"]).startswith("http"):
            raise RegistryError(f"{entry['id']}: source_url must be a full URL")
        if entry["id"] in registry:
            raise RegistryError(f"Duplicate id: {entry['id']}")
        registry[entry["id"]] = entry
    return registry


if __name__ == "__main__":
    reg = load_registry()
    print(f"{len(reg)} indicators loaded")
    for e in reg.values():
        print(f"  {e['id']:<18} {e['source']:<6} {e['source_series']:<10} {e['frequency']}")
