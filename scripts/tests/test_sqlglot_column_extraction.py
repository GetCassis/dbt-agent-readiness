"""Smoke test for the sqlglot-backed SELECT-list column extractor.

Mirrors the pattern of `scripts/test_macro_detection.py`: assertion-style
standalone script, no pytest dependency. Exits nonzero on any failure.

Run directly: `python3 scripts/tests/test_sqlglot_column_extraction.py`
"""
from pathlib import Path
import sys

# Make `scripts/` importable whether run from repo root or scripts/tests/.
HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []


# 1. Plain SELECT a, b, c FROM t
cols, resolved, method = inv._extract_columns_via_sqlglot("SELECT a, b, c FROM t")
results.append(case(
    "plain three-column SELECT",
    cols == ["a", "b", "c"] and resolved and method == "sqlglot",
    f"cols={cols} resolved={resolved} method={method}"))


# 2. Aliased columns
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "SELECT a AS x, b AS y FROM t")
results.append(case(
    "aliased columns use aliases",
    cols == ["x", "y"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 3. Table-qualified columns with JOIN
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "SELECT t.a, u.b FROM t JOIN u ON t.id = u.id")
results.append(case(
    "table-qualified columns strip the qualifier",
    cols == ["a", "b"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 4. SELECT * against a known CTE (passed via known_ctes override)
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "WITH cte AS (SELECT x, y FROM src) SELECT * FROM cte",
    known_ctes={"cte": ["x", "y"]})
results.append(case(
    "SELECT * expands against known_ctes override",
    cols == ["x", "y"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 4b. Same query but no known_ctes override - should discover from AST
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "WITH cte AS (SELECT x, y FROM src) SELECT * FROM cte")
results.append(case(
    "SELECT * expands against AST-discovered CTE",
    cols == ["x", "y"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 5. SELECT * EXCEPT (z) against a known CTE
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "WITH cte AS (SELECT x, y, z FROM src) SELECT * EXCEPT (z) FROM cte")
results.append(case(
    "SELECT * EXCEPT (col) strips excluded columns",
    cols == ["x", "y"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 6. SELECT * against an external source (no CTE) - should be unresolved
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "SELECT * FROM external_source")
results.append(case(
    "SELECT * against external source is unresolved",
    cols == ["*"] and not resolved,
    f"cols={cols} resolved={resolved}"))


# 7. Aggregates with aliases
cols, resolved, method = inv._extract_columns_via_sqlglot(
    "SELECT COUNT(*) as n, SUM(amount) as total FROM t")
results.append(case(
    "aggregate aliases are captured",
    cols == ["n", "total"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 8. Malformed SQL falls through to None
bad = "SELECT ))) from (( where"
result = inv._extract_columns_via_sqlglot(bad)
results.append(case(
    "malformed SQL returns None (fallback signal)",
    result is None,
    f"result={result}"))


# 9. Public extract_sql_columns two-tuple contract preserved
names, count = inv.extract_sql_columns("SELECT a, b, c FROM t")
results.append(case(
    "extract_sql_columns returns two-tuple with correct count",
    names == ["a", "b", "c"] and count == 3,
    f"names={names} count={count}"))


# 10. extract_sql_columns_with_method reports 'sqlglot' path
names, count, method, reason = inv.extract_sql_columns_with_method(
    "SELECT a, b FROM t")
results.append(case(
    "extract_sql_columns_with_method reports sqlglot path",
    method == "sqlglot" and reason is None and names == ["a", "b"],
    f"method={method} reason={reason} names={names}"))


# 11. extract_sql_columns_with_method falls back on parse failure
# Use something that sqlglot truly cannot parse but that still has a SELECT
# so the regex fallback can produce something.
bad_sql = "SELECT a, b, c FROM )))"
names, count, method, reason = inv.extract_sql_columns_with_method(bad_sql)
results.append(case(
    "parse failure routes to regex fallback with reason",
    method == "regex" and reason is not None,
    f"method={method} reason={reason!r}"))


# 12. Unresolvable star: public API returns ([], -1) per legacy contract
names, count = inv.extract_sql_columns("SELECT * FROM external")
results.append(case(
    "unresolvable SELECT * returns ([], -1) via public API",
    names == [] and count == -1,
    f"names={names} count={count}"))


print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
