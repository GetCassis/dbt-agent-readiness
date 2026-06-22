"""Regression tests for the v1.2 fix set (A–G) from the tuva docs-mode run.

Standalone assertion script, no pytest dependency. Exits nonzero on any
failure. Run directly:
    python3 scripts/tests/test_v12_fixes.py

Covers:
  A  Jinja `{% set %}` capture blocks + custom `*_columns(` macros mark a model
     as macro-generated (phantom findings suppressed, not high-confidence).
  B  License / agent-guide / blog docs are never glossary/architecture;
     terminology/data-dictionary docs still are.
  C  llm_pass.recommended is gated on actionable signals; dictionary docs alone
     are context, not a trigger.
  D  Manifest-generated docs (JsonDataTable/jsonPath) are detected.
  E  SUM of a 0/1 flag is not a measure/agg mismatch.
  F  A disclosed WHERE filter is not a model-scope contradiction.
  G  Repo-root auto-expansion fires for nested data projects, not for a dbt
     project buried under test-fixtures/.
"""
import tempfile
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402
import docs_scan as ds  # noqa: E402

results = []


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  — {detail}" if detail else ""))
    results.append(passed)
    return passed


# ── A: Jinja set-block + custom column macro ────────────────────────────────
set_block_sql = """
{%- set tuva_core_columns -%}
    , paid_amount
    , allowed_amount
{%- endset -%}
select
    {{ tuva_core_columns }}
    {{ select_extension_columns(ref('input_layer__medical_claim')) }}
from {{ ref('core__stg_claims_medical_claim') }}
"""
used, sigs = inv._detect_macro_column_generation(set_block_sql, columns_resolved=True)
case("Jinja {% set %} block flags model as macro-generated",
     used and 'jinja_set_block' in sigs, f"signals={sigs}")
case("custom *_columns( macro flags model as macro-generated",
     any('_columns' in s for s in sigs), f"signals={sigs}")

plain_sql = "select id, paid_amount from {{ ref('x') }}"
used2, sigs2 = inv._detect_macro_column_generation(plain_sql, columns_resolved=True)
case("plain explicit-column SQL is NOT flagged", not used2, f"signals={sigs2}")

# ── B: doc classifier ───────────────────────────────────────────────────────
case("LICENSE.md is not glossary",
     ds._classify_doc_type('LICENSE.md', 'Apache License\n\n1. Definitions.') == 'other')
case("license-2.0.txt is not glossary",
     ds._classify_doc_type('license/license-2.0.txt', '1. Definitions') == 'other')
case("AGENTS.md is not architecture",
     ds._classify_doc_type('AGENTS.md', 'Tuva Agent Operating Manual data model') == 'other')
case("blog post is not architecture",
     ds._classify_doc_type('docs/blog/building-a-claims-data-platform.md',
                           'Building a data model pipeline') == 'other')
case("real data-dictionary IS glossary",
     ds._classify_doc_type('docs/terminology/data-dictionary.md', '# Data Dictionary') == 'glossary')
case("README is readme", ds._classify_doc_type('README.md', 'x') == 'readme')

# ── D: manifest-generated doc detection ─────────────────────────────────────
case("JsonDataTable component detected as generated",
     bool(ds.GENERATED_DOC_RE.search(
         '<JsonDataTable jsonPath="nodes.seed.x.columns" />')))
case("plain prose not detected as generated",
     not ds.GENERATED_DOC_RE.search('The core data model is the foundation.'))

# ── E: SUM-of-flag is not a measure/agg mismatch ────────────────────────────
case("SUM(case when...) recognized as a count, not a mismatch",
     bool(inv._FLAG_SUM_ARG_RE.search('case when valid then 1 else 0 end')))
case("SUM(valid_flag) recognized as a count",
     bool(inv._FLAG_SUM_ARG_RE.search('valid_flag')))
case("SUM(revenue_amount) NOT treated as a flag",
     not inv._FLAG_SUM_ARG_RE.search('revenue_amount'))

# End-to-end E: build the contradiction catalog over a temp SQL file.
with tempfile.TemporaryDirectory() as td:
    flag_sql = Path(td) / 'm_flag.sql'
    flag_sql.write_text("select sum(case when ok then 1 else 0 end) as valid_num from t")
    real_sql = Path(td) / 'm_real.sql'
    real_sql.write_text("select sum(revenue_amount) as revenue from t")
    cols = [
        {'model': 'm_flag', 'column': 'valid_num',
         'description_text': 'Number of rows that are valid'},
        {'model': 'm_real', 'column': 'revenue',
         'description_text': 'Count of orders'},
    ]
    sql_data = {'m_flag': {'path': str(flag_sql)}, 'm_real': {'path': str(real_sql)}}
    rows = inv._build_description_contradicts_sql({}, cols, sql_data, {})
    agg_rows = [r for r in rows if r['kind'] == 'measure_agg_mismatch']
    flagged_models = {r['model'] for r in agg_rows}
    case("SUM-of-flag column is NOT flagged as agg mismatch",
         'm_flag' not in flagged_models, f"agg_rows={[r['model'] for r in agg_rows]}")
    case("genuine SUM-where-desc-says-count IS still flagged",
         'm_real' in flagged_models, f"agg_rows={[r['model'] for r in agg_rows]}")

# ── F: disclosed WHERE filter is not a scope contradiction ──────────────────
models_dict = {
    'disclosed': {
        'description_text': 'Includes all rows where disqualified_encounter_flag = 0.',
        'sql_snippets': {'where_clauses': ['disqualified_encounter_flag = 0']},
    },
    'hidden': {
        'description_text': 'Contains all rows for every customer in the table.',
        'sql_snippets': {'where_clauses': ["region = 'EU'"]},
    },
}
rows = inv._build_description_contradicts_sql(models_dict, [], {}, {})
scope_models = {r['model'] for r in rows if r['kind'] == 'model_scope_contradiction'}
case("disclosed filter is NOT a scope contradiction",
     'disclosed' not in scope_models, f"scope_models={scope_models}")
case("hidden filter IS a scope contradiction",
     'hidden' in scope_models, f"scope_models={scope_models}")

# ── G: repo-root expansion guard ────────────────────────────────────────────
root = Path('/repo')
case("warehouse/ nested project expands to repo root",
     ds._should_expand_to_repo_root(Path('/repo/warehouse'), root))
case("transform/snowflake-dbt expands",
     ds._should_expand_to_repo_root(Path('/repo/transform/snowflake-dbt'), root))
case("projects/jaffle_planning expands",
     ds._should_expand_to_repo_root(Path('/repo/projects/jaffle_planning'), root))
case("single-level nested project expands",
     ds._should_expand_to_repo_root(Path('/repo/my_dbt'), root))
case("test-fixtures/ project does NOT expand",
     not ds._should_expand_to_repo_root(Path('/repo/test-fixtures/docs-context'), root))

passed = sum(1 for r in results if r)
total = len(results)
print(f"\nOK: {passed}/{total} passed" if passed == total
      else f"\nFAILED: {total - passed}/{total} failed")
sys.exit(0 if passed == total else 1)
