"""Regression tests for undefined_column_refs false-positive suppression.

Covers the parser blind spots that produced wall-of-noise findings on real
Snowflake / macro-heavy projects (v1.2.0):
  - SQL date-part keywords inside DATEADD/DATEDIFF/DATE_TRUNC
  - UNPIVOT value/name output columns
  - lateral table-function (SPLIT_TO_TABLE) system columns
  - fivetran_utils.fill_staging_columns macro-generated column sets
  - ref()/CTE name collisions (ref resolves to the model, not a same-name CTE)
  - the Jinja-expression sentinel propagating as an unresolvable shape

A genuinely undefined column must still fire (no over-suppression), including
one inside a model that also uses UNPIVOT.

Assertion-style standalone script, no pytest dependency. Exits nonzero on any
failure. Run directly:
    python3 scripts/tests/test_undefined_column_refs.py
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402

FIXTURE = (HERE.parent.parent.parent
           / 'test-fixtures' / 'sql-edge-cases')


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []

# ── Unit: helper extraction ────────────────────────────────────────────────
up = inv._unpivot_output_cols(
    "select a, b from t unpivot(val for name in (x, y, z))")
results.append(case(
    "_unpivot_output_cols captures value + name",
    up == {"val", "name"}, f"got={sorted(up)}"))

up2 = inv._unpivot_output_cols(
    "select * from t unpivot((v1, v2) for cat in ((a, b), (c, d)))")
results.append(case(
    "_unpivot_output_cols handles comma value form",
    {"v1", "v2", "cat"} <= up2, f"got={sorted(up2)}"))

extra = inv._model_produced_extra_cols(
    "select id, value from t, lateral split_to_table(t.s, ',')")
results.append(case(
    "_model_produced_extra_cols adds lateral system cols",
    "value" in extra, f"got={sorted(extra)}"))

results.append(case(
    "date-part keywords are in the denylist",
    {"day", "month", "quarter", "week", "hour", "minute"} <= inv._SQL_DATE_PARTS,
    ""))

# ── Integration: run the whole inventory on the edge-case fixture ───────────
inv_out = inv.build_inventory(FIXTURE)
ucr = inv_out.get('catalogs', {}).get('undefined_column_refs', [])
fired = {(r['model'], r['column']) for r in ucr}

expected = {
    ('undefined_true_positive', 'nonexistent_column'),
    ('unpivot_true_positive', 'bogus_total'),
}
results.append(case(
    "exactly the two genuine undefined columns fire",
    fired == expected,
    f"fired={sorted(fired)}"))

# Each "ok" model must be silent — these are the blind spots being fixed.
ok_models = {
    'date_parts_ok': 'DATEADD/DATE_TRUNC date-part tokens',
    'unpivot_ok': 'UNPIVOT value/name outputs',
    'fill_staging_ok': 'fivetran_utils.fill_staging_columns',
    'lateral_ok': 'lateral SPLIT_TO_TABLE value column',
}
fired_models = {m for m, _ in fired}
for model, why in ok_models.items():
    results.append(case(
        f"{model} produces no false positive ({why})",
        model not in fired_models,
        f"unexpected: {sorted(c for m, c in fired if m == model)}"))

# The legit UNPIVOT outputs in the true-positive model must NOT also fire.
results.append(case(
    "unpivot_true_positive flags only bogus_total, not period/sales_amount",
    {c for m, c in fired if m == 'unpivot_true_positive'} == {'bogus_total'},
    ""))

print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
