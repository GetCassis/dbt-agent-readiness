"""Advanced sqlglot-migration smoke tests for inventory.py.

Standalone script style matching `test_macro_detection.py` and
`test_sqlglot_column_extraction.py`. Assertions, no pytest dep. Exits
nonzero on any failure.

Run: `python3 scripts/tests/test_sqlglot_advanced.py`
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []


# 1. Nested CTEs 3 levels deep. `top` traces through `mid` through `base`.
sql = """
WITH base AS (SELECT a, b, loyalty_tier FROM raw),
     mid AS (SELECT * FROM base),
     top AS (SELECT * FROM mid)
SELECT * FROM top
"""
cols, resolved, method = inv._extract_columns_via_sqlglot(sql)
results.append(case(
    "nested CTEs 3 levels deep trace through base/mid/top",
    cols == ["a", "b", "loyalty_tier"] and resolved and method == "sqlglot",
    f"cols={cols} resolved={resolved}"))


# 2. Window function + QUALIFY
sql = "SELECT x, ROW_NUMBER() OVER (PARTITION BY y ORDER BY z) AS rn FROM t QUALIFY rn = 1"
cols, resolved, method = inv._extract_columns_via_sqlglot(sql, dialect='bigquery')
results.append(case(
    "window function + QUALIFY yields named columns",
    cols == ["x", "rn"] and resolved,
    f"cols={cols} resolved={resolved}"))


# 3. Nested CASE WHEN column references captured via filter_refs
sql = """
SELECT id,
       CASE WHEN status = 'active'
            THEN (CASE WHEN tier = 'gold' THEN priority ELSE note END)
            ELSE category END AS result
FROM t
"""
refs = inv._extract_filter_refs(sql)
case_cols = set(refs['case_cols'])
results.append(case(
    "nested CASE WHEN captures all referenced columns",
    {'status', 'tier', 'priority', 'note', 'category'}.issubset(case_cols),
    f"case_cols={sorted(case_cols)}"))


# 4. BigQuery STRUCT / UNNEST with dialect
sql = "SELECT a.b FROM t, UNNEST(t.arr) a"
cols, resolved, method = inv._extract_columns_via_sqlglot(sql, dialect='bigquery')
results.append(case(
    "BigQuery UNNEST parses and extracts column",
    method == 'sqlglot' and cols == ["b"],
    f"cols={cols} method={method}"))


# 5. Snowflake LATERAL FLATTEN
sql = "SELECT f.value FROM t, LATERAL FLATTEN(input => t.arr) f"
cols, resolved, method = inv._extract_columns_via_sqlglot(sql, dialect='snowflake')
results.append(case(
    "Snowflake LATERAL FLATTEN parses successfully",
    method == 'sqlglot' and cols == ["value"],
    f"cols={cols} method={method}"))


# 6. DuckDB PIVOT (sqlglot may produce a non-Select root; just verify no crash
#    and that the module-level public API doesn't throw).
sql = "PIVOT sales ON category USING sum(amount)"
try:
    names, count, method, reason = inv.extract_sql_columns_with_method(
        sql, dialect='duckdb')
    passed = True
except Exception as exc:
    passed = False
    names = count = method = reason = None
results.append(case(
    "DuckDB PIVOT does not crash the extractor",
    passed,
    f"names={names} method={method} reason={reason}"))


# 7. Cross-project ref. Jinja-stripped SQL treats `their_model` as the table.
raw_sql = "SELECT * FROM {{ ref('other_proj', 'their_model') }}"
stripped = inv.strip_jinja_comments(raw_sql)
# After Jinja strip, sqlglot can at least parse; output is unresolvable star
cols, resolved, method = inv._extract_columns_via_sqlglot(stripped)
results.append(case(
    "cross-project ref after Jinja strip parses",
    method == 'sqlglot' and cols == ['*'] and not resolved,
    f"cols={cols} resolved={resolved} method={method}"))


# 8. SELECT * EXCEPT (col_a, col_b) FROM upstream
sql = """
WITH upstream AS (SELECT a, b, col_a, col_b FROM raw)
SELECT * EXCEPT (col_a, col_b) FROM upstream
"""
cols, resolved, method = inv._extract_columns_via_sqlglot(sql)
results.append(case(
    "SELECT * EXCEPT excludes listed columns",
    cols == ["a", "b"] and resolved,
    f"cols={cols}"))


# 9. CTE chain > 1 level: loyalty_tier stays resolvable, not phantom.
sql = """
WITH base AS (SELECT loyalty_tier FROM src),
     mid AS (SELECT * FROM base)
SELECT * FROM mid
"""
cols, resolved, method = inv._extract_columns_via_sqlglot(sql)
results.append(case(
    "loyalty_tier resolves through 2-hop CTE chain",
    cols == ["loyalty_tier"] and resolved,
    f"cols={cols}"))


# 10. Jinja-macro-heavy model: after stripping, SQL parses and method == 'sqlglot'.
sql = """
{% set cols = ['a','b'] %}
{{ config(materialized='view') }}
SELECT
  {% for c in cols %}{{ c }}{% if not loop.last %},{% endif %}{% endfor %},
  extra
FROM t
"""
# Note: after Jinja strip the comprehension collapses to whitespace. The tail
# `,extra FROM t` is what remains. Accept either 'sqlglot' or fallback to
# regex, but the goal is that it at least doesn't crash.
names, count, method, reason = inv.extract_sql_columns_with_method(sql)
results.append(case(
    "jinja-heavy model parses via sqlglot or falls back cleanly",
    method in ('sqlglot', 'regex'),
    f"names={names} method={method} reason={reason}"))


# 11. Incremental with is_incremental() guard. Stripped Jinja still parses.
sql = """
SELECT a, b FROM t
{% if is_incremental() %}
WHERE updated_at > (SELECT max(updated_at) FROM {{ this }})
{% endif %}
"""
names, count, method, reason = inv.extract_sql_columns_with_method(sql)
results.append(case(
    "incremental is_incremental() guard parses after strip",
    method == 'sqlglot' and names == ['a', 'b'],
    f"names={names} method={method}"))


# 12. Unit drift detection: amount_cents / 100.0 AS amount.
sql = "SELECT amount_cents / 100.0 AS amount FROM src"
hits = inv._extract_unit_drift(sql)
results.append(case(
    "unit drift scanner finds amount_cents / 100.0",
    len(hits) == 1 and hits[0]['column'] == 'amount_cents'
    and hits[0]['aliased_as'] == 'amount',
    f"hits={hits}"))


failed = sum(1 for r in results if not r)
total = len(results)
print()
if failed:
    print(f"FAIL: {failed}/{total} cases failed")
    sys.exit(1)
print(f"OK: {total}/{total} passed")
