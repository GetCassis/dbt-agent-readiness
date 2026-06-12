"""Regression tests for fan_out_joins uniqueness-coverage (v1.3.0).

Covers the false-positive class where a model declares uniqueness through a
model-level dbt_utils.unique_combination_of_columns test (column tuple),
including tests attached via a YAML anchor alias. A downstream join on the
whole tuple (or a superset) must NOT be flagged; a join on a strict subset of
the tuple still can fan out and MUST stay flagged; a join key with no
uniqueness guarantee MUST stay flagged (regression guard).

Assertion-style standalone script, no pytest dependency. Exits nonzero on any
failure. Run directly:
    python3 scripts/tests/test_fan_out_joins.py
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402

FIXTURE = HERE.parent.parent.parent / 'test-fixtures' / 'fan-out-joins'


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []

# ── Unit: the tuple extractor across the syntaxes it must recognize ─────────
classic = inv._extract_unique_combinations(
    [{'dbt_utils.unique_combination_of_columns':
      {'combination_of_columns': ['A', 'b']}}])
results.append(case(
    "extractor handles classic combination_of_columns",
    classic == [frozenset({'a', 'b'})], f"got={classic}"))

args_form = inv._extract_unique_combinations(
    [{'dbt_utils.unique_combination_of_columns':
      {'arguments': {'combination_of_columns': ['dt', 'base64_url']}}}])
results.append(case(
    "extractor handles nested arguments: syntax",
    args_form == [frozenset({'dt', 'base64_url'})], f"got={args_form}"))

noise = inv._extract_unique_combinations(
    [{'not_null': {}}, 'unique', None,
     {'dbt_utils.expression_is_true': {'expression': 'x > 0'}}])
results.append(case(
    "extractor ignores non-combination tests",
    noise == [], f"got={noise}"))

# ── Integration: run the whole inventory on the fixture ─────────────────────
out = inv.build_inventory(FIXTURE)
fo = out.get('catalogs', {}).get('fan_out_joins', [])
fired = {(r['model'], r['join_column']) for r in fo}

expected = {
    ('dim_subset_combo', 'region_id'),
    ('dim_no_test', 'region_id'),
}
results.append(case(
    "exactly the two genuine fan-outs fire",
    fired == expected,
    f"fired={sorted(fired)}"))

fired_models = {m for m, _ in fired}
results.append(case(
    "dim_unique_combo suppressed (join covers the unique tuple)",
    'dim_unique_combo' not in fired_models,
    f"unexpected: {sorted(c for m, c in fired if m == 'dim_unique_combo')}"))
results.append(case(
    "dim_anchor_combo suppressed (tuple test via YAML anchor alias)",
    'dim_anchor_combo' not in fired_models,
    f"unexpected: {sorted(c for m, c in fired if m == 'dim_anchor_combo')}"))
results.append(case(
    "dim_subset_combo still fires (subset join can fan out)",
    ('dim_subset_combo', 'region_id') in fired, ""))
results.append(case(
    "dim_no_test still fires (no uniqueness guarantee)",
    ('dim_no_test', 'region_id') in fired, ""))

# The unique-combination tuple is parsed onto the model from the schema.
idx = {m['name']: m for m in out['models']}
results.append(case(
    "model-level tuple parsed via anchor alias",
    [sorted(c) for c in idx.get('dim_anchor_combo', {}).get(
        'unique_combinations', [])] == [['day', 'region_id']],
    f"got={idx.get('dim_anchor_combo', {}).get('unique_combinations')}"))

print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
