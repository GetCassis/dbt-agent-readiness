"""Smoke test for _detect_macro_column_generation and phantom confidence.

Run directly: `python scripts/test_macro_detection.py`
Exits nonzero on any assertion failure. No external deps.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import inventory as inv  # noqa: E402


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  — {detail}" if detail else ""))
    return passed


results = []

# 1. Bare SELECT * at final level, no resolution context → provisional
sql = "SELECT * FROM raw_table"
used, sigs = inv._detect_macro_column_generation(sql, columns_resolved=False)
results.append(case(
    "bare SELECT * with columns_resolved=False → provisional",
    used and "select_star" in sigs,
    f"signals={sigs}"))

# 2. Same SQL but columns_resolved=True → clean
used, sigs = inv._detect_macro_column_generation(sql, columns_resolved=True)
results.append(case(
    "bare SELECT * with columns_resolved=True → high",
    not used,
    f"signals={sigs}"))

# 3. dbt_utils.star with columns_resolved=True → still provisional
sql = "SELECT {{ dbt_utils.star(from=ref('x')) }} FROM {{ ref('x') }}"
used, sigs = inv._detect_macro_column_generation(sql, columns_resolved=True)
results.append(case(
    "dbt_utils.star still flags even when columns_resolved=True",
    used and any("star" in s for s in sigs),
    f"signals={sigs}"))

# 4. Jinja for-loop → still provisional regardless
sql = """SELECT
  {% for metric in metrics %}
    , {{ metric }} as metric_value
  {% endfor %}
  id
FROM t"""
used, sigs = inv._detect_macro_column_generation(sql, columns_resolved=True)
results.append(case(
    "jinja for-loop still flags even when columns_resolved=True",
    used and "jinja_for_loop" in sigs,
    f"signals={sigs}"))

# 5. End-to-end: local CTE SELECT * → extract_sql_columns resolves + phantom row is `high`
sql = """
with src as (
    select a, b, c from raw
),
final as (
    select
        a,
        b as alias_b,
        c
    from src
)
select * from final
"""
names, count = inv.extract_sql_columns(sql)
results.append(case(
    "extract_sql_columns resolves SELECT * FROM local_cte",
    count == 3 and set(names) >= {"a", "c"},
    f"names={names} count={count}"))

# Simulate _build_phantom_by_model path directly
import tempfile
with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as tf:
    tf.write(sql)
    sql_path = tf.name

issues = {"phantom_columns": [
    {"model": "final_model", "column": "phantom_col", "yaml_path": "x.yml"}
]}
sql_data = {"final_model": {
    "path": sql_path,
    "columns": names,
    "column_count": count,
}}
rows, suppressed = inv._build_phantom_by_model(
    issues, sql_data=sql_data, manifest_used=False)
row = rows[0] if rows else {}
results.append(case(
    "phantom row for resolvable SELECT * is emitted with 'high' confidence",
    row.get("confidence") == "high" and not suppressed,
    f"row={row} suppressed={suppressed}"))

# 6. Unresolvable SELECT * (references external ref, not a local CTE) →
# suppressed (not emitted as a finding). Previously this was emitted as
# `provisional`; as of the phantom-suppression change we instead return
# it in the `suppressed` list so the report can emit a single "run
# `dbt compile`" notice rather than noisy per-model rows.
sql_unres = "SELECT * FROM {{ ref('external_model') }}"
with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as tf:
    tf.write(sql_unres)
    sql_path = tf.name
names2, count2 = inv.extract_sql_columns(sql_unres)
issues = {"phantom_columns": [
    {"model": "unres_model", "column": "phantom_col", "yaml_path": "x.yml"}
]}
sql_data = {"unres_model": {
    "path": sql_path,
    "columns": names2,
    "column_count": count2,
}}
rows, suppressed = inv._build_phantom_by_model(
    issues, sql_data=sql_data, manifest_used=False)
sup = suppressed[0] if suppressed else {}
results.append(case(
    "phantom row for unresolvable SELECT * is suppressed (not emitted)",
    not rows
    and sup.get("model") == "unres_model"
    and "select_star" in sup.get("macro_signals", []),
    f"rows={rows} suppressed={suppressed}"))

print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
