"""Regression test for phantom-column false positives on Jinja-for-loop columns
when a compiled manifest is present (v1.4.0).

Bug: phantom detection upgraded SQL *snippets* to the manifest's compiled_code
but still derived the column set from raw Jinja-stripped SQL. A for-loop body
like `{{ pm }}_amount` strips to a single `_amount` token, so the real generated
columns were flagged high-confidence phantom even though the manifest resolves
them. Fix: re-extract columns from compiled_code when available.

The fixture `test-fixtures/manifest-forloop/` ships a for-loop model plus a
hand-written target/manifest.json whose compiled_code lists the real columns,
and one genuine phantom (`legacy_total`) that must still fire.

Assertion-style standalone script, no pytest. Run directly:
    python3 scripts/tests/test_phantom_manifest.py
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402

FIXTURE = HERE.parent.parent.parent / 'test-fixtures' / 'manifest-forloop'


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []
out = inv.build_inventory(FIXTURE)

results.append(case("manifest with compiled_code is used",
                    out['manifest_used'] is True))

orders = next((m for m in out['models'] if m['name'] == 'orders'), None)
results.append(case("orders column_count_sql comes from compiled (4, not the "
                    "mangled raw count)",
                    bool(orders) and orders['column_count_sql'] == 4,
                    f"got={orders and orders['column_count_sql']}"))

pbm = {r['model']: set(r['phantoms'])
       for r in out['catalogs'].get('phantom_columns_by_model', [])}
orders_phantoms = pbm.get('orders', set())

results.append(case("for-loop columns NOT flagged phantom (the fix)",
                    not ({'credit_card_amount', 'coupon_amount'} & orders_phantoms),
                    f"orders_phantoms={sorted(orders_phantoms)}"))
results.append(case("total_amount NOT flagged phantom",
                    'total_amount' not in orders_phantoms))
results.append(case("genuine phantom legacy_total still flagged",
                    'legacy_total' in orders_phantoms,
                    f"orders_phantoms={sorted(orders_phantoms)}"))

# The phantom that remains must carry high confidence (manifest present).
hi = {p for r in out['catalogs'].get('phantom_columns_by_model', [])
      if r.get('confidence') == 'high' for p in r['phantoms']}
results.append(case("remaining phantom is high-confidence",
                    'legacy_total' in hi))

print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
