import ast
from pathlib import Path

# app.py runs Streamlit on import, so load just the pure helper from its source.
_src = (Path(__file__).resolve().parent.parent / "app" / "app.py").read_text(encoding="utf-8-sig")
_fn = next(n for n in ast.parse(_src).body if isinstance(n, ast.FunctionDef) and n.name == "inr_group")
_ns: dict = {}
exec(compile(ast.Module([_fn], type_ignores=[]), "app.py", "exec"), _ns)
inr_group = _ns["inr_group"]


def test_indian_grouping():
    assert inr_group(123893) == "1,23,893"
    assert inr_group(999) == "999"
    assert inr_group(1234) == "1,234"
    assert inr_group(12345678) == "1,23,45,678"
    assert inr_group(-100000) == "-1,00,000"
