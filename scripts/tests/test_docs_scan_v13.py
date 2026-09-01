"""Regression tests for the docs_scan v1.3 fix set, surfaced by the full-funnel
docs-mode run.

Standalone assertion script, no pytest dependency. Exits nonzero on any
failure. Run directly:
    python3 scripts/tests/test_docs_scan_v13.py

Covers:
  A  Column-claim extraction is limited to column-dictionary tables. A generic
     key/value metadata table (`| Property | Value |`, `| Setting | Value |`)
     under a model heading no longer leaks its header word as a claimed column
     (the bug that broadcast a phantom `property` column onto ~29 models and
     inflated column_drift / the doc-column LLM queue). A table header row is
     never itself emitted as a column.
  B  Doc paths use one consistent base (the smallest dir containing the project
     anchor + all docs), so a doc inside the dbt project is no longer cited as a
     bare `README.md`; and byte-identical docs are deduped so their identifiers,
     claims, and pointers are not double counted.
"""
import tempfile
from datetime import date
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402
import docs_scan as ds  # noqa: E402

TODAY = date(2026, 1, 1)
results = []


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  — {detail}" if detail else ""))
    results.append(passed)
    return passed


# ── A: column-claim extraction is table-aware ───────────────────────────────
property_kv = """
| Property | Value |
|----------|-------|
| **File** | `models/x.sql` |
| **Materialization** | view |
| **Source** | `olist.orders` |
"""
case("Property|Value metadata table yields no claimed columns",
     ds._extract_column_table_claims(property_kv) == [],
     f"got={ds._extract_column_table_claims(property_kv)}")

setting_kv = """
| Setting | Value |
|---------|-------|
| timeout | 30 |
"""
case("Setting|Value metadata table yields no claimed columns",
     ds._extract_column_table_claims(setting_kv) == [],
     f"got={ds._extract_column_table_claims(setting_kv)}")

real_cols = """
| Column | Type | Description |
|--------|------|-------------|
| `order_id` | VARCHAR | PK |
| `customer_id` | VARCHAR | FK |
"""
got = ds._extract_column_table_claims(real_cols)
case("real Column|Type table yields its columns",
     got == ['customer_id', 'order_id'], f"got={got}")
case("table header word is never emitted as a column",
     'column' not in got and 'property' not in got, f"got={got}")

your_col = """
| Your column | dbt staging name | Type |
|-------------|------------------|------|
| Impressions | `impressions` | INT64 |
| Clicks | `clicks` | INT64 |
| Campaign name | `campaign_name` | STRING |
"""
got = ds._extract_column_table_claims(your_col)
case("column table detected via a Type column header",
     got == ['clicks', 'impressions'], f"got={got}")  # 'Campaign name' has a space

fenced = """
```
some_snake_col other_snake
```
"""
case("fenced snake_case tokens still captured",
     'some_snake_col' in ds._extract_column_table_claims(fenced))

case("_is_md_sep_row recognizes a separator row",
     ds._is_md_sep_row(['---', ':---:']) and not ds._is_md_sep_row(['Property']))
case("_is_column_table_header true for Column/Type, false for Property/Value",
     ds._is_column_table_header(['Column', 'Type'])
     and not ds._is_column_table_header(['Property', 'Value']))

# End-to-end: a model section with BOTH a Property|Value table and a column table
doc = """
## `dim_customers`

| Property | Value |
|----------|-------|
| Materialization | table |

| Column | Type |
|--------|------|
| `customer_id` | VARCHAR |
| `email` | VARCHAR |
"""
claims = ds._extract_doc_column_claims(doc, {'dim_customers'})
cols = claims[0]['claimed_columns'] if claims else []
case("doc claims = real columns only, no 'property'",
     cols == ['customer_id', 'email'], f"got={cols}")

# ── B: consistent path base + byte-identical dedup ──────────────────────────
_tmpdir = tempfile.TemporaryDirectory()
tmp = Path(_tmpdir.name)
try:
    (tmp / 'dbt_project.yml').write_text(
        'name: tmptest\nprofile: tmptest\nmodel-paths: ["models"]\n')
    (tmp / 'models' / 'marts').mkdir(parents=True)
    (tmp / 'models' / 'marts' / 'dim_x.sql').write_text('select 1 as id, 2 as val\n')
    (tmp / 'models' / 'schema.yml').write_text(
        'version: 2\nmodels:\n  - name: dim_x\n')
    docs = tmp / 'docs'
    (docs / 'sub').mkdir(parents=True)
    dup_text = '# Notes\n\nDocumentation about `dim_x`.\n'
    (docs / 'a.md').write_text(dup_text)
    (docs / 'b.md').write_text(dup_text)                # byte-identical -> deduped
    (docs / 'sub' / 'c.md').write_text('# Other\n\nRevenue notes.\n')  # distinct, nested

    inventory = inv.build_inventory(tmp)
    out = ds.scan(tmp, inventory, doc_sources=['docs'], today=TODAY)
    dc = out['doc_corpus']
    paths = {x['path'] for x in dc['docs']}

    case("byte-identical doc is deduped (1 dup, 2 unique scanned)",
         dc['scanned'] == 2 and len(dc['duplicate_content']) == 1,
         f"scanned={dc['scanned']} dups={dc['duplicate_content']}")
    dup = dc['duplicate_content'][0] if dc['duplicate_content'] else {}
    case("the dup records what it duplicates",
         {dup.get('path'), dup.get('duplicate_of')} <= {'docs/a.md', 'docs/b.md'},
         f"dup={dup}")
    case("nested doc keeps its full dir prefix (no bare path)",
         'docs/sub/c.md' in paths,
         f"paths={sorted(paths)}")
    case("path_base is the project root",
         Path(dc['path_base']).resolve() == tmp.resolve(),
         f"path_base={dc['path_base']}")
finally:
    _tmpdir.cleanup()

# ── C: semantic-layer metric/measure descriptions are authoritative ─────────
# inventory carries the boolean under `has_description`; docs_scan must read that
# (not a `description` key) or every described metric looks undefined and its
# prose contradictions over-escalate from Hygiene to Blocker.
inv_stub = {
    'models': [], 'columns': [],
    'semantic_layer': {
        'metrics': [
            {'name': 'session_conversion_rate', 'has_description': True},
            {'name': 'undocumented_metric', 'has_description': False},
        ],
        'semantic_models': [
            {'name': 'm', 'measures': [{'name': 'revenue', 'has_description': True}]},
        ],
    },
}
_cu, _su, lookup, _m, _c = ds._build_identifier_facts(inv_stub)
scv = lookup.get('session_conversion_rate') or {}
case("described metric is an authoritative dbt definition",
     scv.get('authoritative_dbt_definition', {}).get('exists') is True
     and scv['authoritative_dbt_definition'].get('source') == 'semantic_metric',
     f"got={scv.get('authoritative_dbt_definition')}")
undoc = lookup.get('undocumented_metric') or {}
case("undescribed metric is NOT authoritative",
     undoc.get('authoritative_dbt_definition', {}).get('exists') is False,
     f"got={undoc.get('authoritative_dbt_definition')}")
meas = lookup.get('revenue') or {}
case("described measure is an authoritative dbt definition",
     meas.get('authoritative_dbt_definition', {}).get('exists') is True,
     f"got={meas.get('authoritative_dbt_definition')}")

passed = sum(1 for r in results if r)
total = len(results)
print(f"\nOK: {passed}/{total} passed" if passed == total
      else f"\nFAILED: {total - passed}/{total} failed")
sys.exit(0 if passed == total else 1)
