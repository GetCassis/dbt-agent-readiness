"""Regression tests for the docs-scan capability (v1.5.0).

Deterministic gate over the planted `test-fixtures/docs-context/` project. Pins
Layer-1 detection of every planted signal: coverage gap, doc-vs-code column
drift, multi-home candidates (with the two facts the reliability rule needs),
off-repo pointers, staleness, and the dbt-layer boundary exclusion.

The agree/differ verdict on doc-vs-doc disagreements is the Layer-2 LLM's job
and is intentionally NOT asserted here.

Assertion-style standalone script, no pytest dependency. Exits nonzero on any
failure. Run directly:
    python3 scripts/tests/test_docs_scan.py
"""
from datetime import date
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))
import inventory as inv  # noqa: E402
import docs_scan as ds  # noqa: E402

FIXTURE = HERE.parent.parent.parent / 'test-fixtures' / 'docs-context'
TODAY = date(2026, 6, 19)


def case(name, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    print(f"  {status}  {name}" + (f"  - {detail}" if detail else ""))
    return passed


results = []

# ── Unit: dbt-layer boundary helpers ────────────────────────────────────────
results.append(case(
    "doc-block file detected by content",
    ds._is_dbt_doc_block_file("{% docs x %}body{% enddocs %}") is True))
results.append(case(
    "plain prose is not a doc-block file",
    ds._is_dbt_doc_block_file("# Just a heading\nsome prose") is False))

# ── Build inventory once, run the scan over the external docs ────────────────
inventory = inv.build_inventory(FIXTURE)
out = ds.scan(FIXTURE, inventory, doc_sources=['docs'], today=TODAY)

# ── 1. Correct doc matched, coverage gap exact ──────────────────────────────
cov = out['identifier_coverage']
results.append(case(
    "dim_customers counted as documented",
    'dim_customers' in cov['documented_list'], f"documented={cov['documented_list']}"))
results.append(case(
    "stg_customers counted as undocumented (coverage gap)",
    'stg_customers' in cov['undocumented_list'],
    f"undocumented={cov['undocumented_list']}"))
results.append(case(
    "undocumented source tables listed",
    {'customer_events', 'order_events'} <= set(cov['undocumented_list'])))

# ── 2. doc-vs-code column drift (high confidence), no false drift ────────────
drift = out['column_drift']
fct_orders_drift = [d for d in drift if d['model'] == 'fct_orders']
results.append(case(
    "fct_orders order_total flagged as drift",
    bool(fct_orders_drift)
    and 'order_total' in fct_orders_drift[0]['claimed_not_in_model'],
    f"drift={[(d['model'], d['claimed_not_in_model']) for d in drift]}"))
results.append(case(
    "fct_orders drift is high confidence (YAML mirrors SQL)",
    bool(fct_orders_drift) and fct_orders_drift[0]['confidence'] == 'high',
    f"conf={[d['confidence'] for d in fct_orders_drift]}"))
results.append(case(
    "no false drift on the correctly-documented dim_customers",
    all(d['model'] != 'dim_customers' for d in drift)))
results.append(case(
    "real column order_amount not flagged as drift",
    all('order_amount' not in d['claimed_not_in_model'] for d in drift)))

# ── 3/4. Multi-home candidates carry the reliability-rule facts ─────────────
mh = {m['identifier']: m for m in out['multi_home_candidates']}
rev = mh.get('fct_revenue')
results.append(case(
    "fct_revenue is a multi-home candidate",
    rev is not None and rev['doc_count'] >= 2, f"got={rev}"))
results.append(case(
    "fct_revenue: dbt identifier with NO authoritative definition (Blocker-eligible)",
    bool(rev) and rev['is_dbt_identifier'] is True
    and rev['authoritative_dbt_definition']['exists'] is False))
dimc = mh.get('dim_customers')
results.append(case(
    "dim_customers: multi-home but authoritative dbt definition exists (Hygiene)",
    bool(dimc) and dimc['authoritative_dbt_definition']['exists'] is True))

# The reliability rule synthesis will apply, pinned on the deterministic inputs.
def blocker_eligible(c):
    return c['is_dbt_identifier'] and not c['authoritative_dbt_definition']['exists']
results.append(case(
    "reliability rule: fct_revenue eligible, dim_customers not",
    blocker_eligible(rev) and not blocker_eligible(dimc)))

# ── 3b. severity_if_differ: conditional severity per agent grounding model ───
# v1.6.0 reliability rework. A dbt-pinned `differ` is a Blocker for a
# repo-grounded agent (reads dbt AND docs, no rule for which side wins) but
# Hygiene for a metadata-grounded agent (answers from the dbt layer). A
# no-fallback `differ` is a Blocker for both. The label is conditional, not one
# fixed archetype.
results.append(case(
    "every multi-home candidate carries a severity_if_differ map",
    all('severity_if_differ' in m
        and set(m['severity_if_differ']) == {'repo_grounded', 'metadata_grounded'}
        for m in out['multi_home_candidates'])))
results.append(case(
    "dbt-pinned differ: Blocker for repo-grounded, Hygiene for metadata-grounded",
    bool(dimc) and dimc['severity_if_differ'] == {
        'repo_grounded': 'blocker', 'metadata_grounded': 'hygiene'},
    f"got={dimc.get('severity_if_differ') if dimc else None}"))
results.append(case(
    "no-fallback differ: Blocker for both archetypes",
    bool(rev) and rev['severity_if_differ'] == {
        'repo_grounded': 'blocker', 'metadata_grounded': 'blocker'},
    f"got={rev.get('severity_if_differ') if rev else None}"))

# ── 5. Off-repo pointers ────────────────────────────────────────────────────
ext = out['external_pointers']
results.append(case(
    "google docs + confluence pointers counted",
    ext['by_category'].get('google_docs', 0) >= 1
    and ext['by_category'].get('confluence', 0) >= 1,
    f"by_cat={ext['by_category']}"))
results.append(case(
    "doc that defers authority offsite is flagged",
    'docs/legacy-pipeline.md' in ext['defers_authority_offsite_docs']))

# ── 6. Staleness ────────────────────────────────────────────────────────────
stale = {s['path']: s for s in out['staleness_flags']}
lp = stale.get('docs/legacy-pipeline.md')
results.append(case(
    "legacy-pipeline flagged stale by date and deprecated marker",
    bool(lp) and lp['stale_by_date'] is True and 'deprecated' in lp['markers'],
    f"got={lp}"))

# ── 7. doc_column_claims captured ───────────────────────────────────────────
claims = {c['model'] for c in out['doc_column_claims']}
results.append(case(
    "doc_column_claims captured for fct_orders",
    'fct_orders' in claims, f"claims for={claims}"))

# ── 8. LLM queue carries ONLY Blocker-eligible (no-fallback) candidates ──────
q = out['llm_queue']
results.append(case(
    "llm_queue leads with a Blocker-eligible multi-home candidate",
    bool(q['multi_home'])
    and q['multi_home'][0]['authoritative_dbt_definition']['exists'] is False))
results.append(case(
    "llm_queue carries ONLY no-fallback candidates (Hygiene ones not sent)",
    all(c['authoritative_dbt_definition']['exists'] is False
        for c in q['multi_home'])))
results.append(case(
    "Hygiene-only multi-home candidates are routed away from the LLM, not dropped",
    q['dropped_beyond_cap'].get('multi_home_hygiene_only_not_sent', 0) >= 1))
results.append(case(
    "nothing dropped purely by the cap (fixture is small)",
    q['dropped_beyond_cap']['multi_home'] == 0
    and q['dropped_beyond_cap']['doc_column_claims'] == 0
    and q['dropped_beyond_cap']['doc_classification'] == 0,
    f"dropped={q['dropped_beyond_cap']}"))

# ── 9. dbt-layer boundary exclusion under auto-discovery ────────────────────
auto = ds.scan(FIXTURE, inventory, doc_sources=None, today=TODAY)
scanned_paths = [d['path'] for d in auto['doc_corpus']['docs']]
results.append(case(
    "README + doc-block file excluded from external corpus",
    not any('README' in p for p in scanned_paths)
    and not any('_models_docs' in p for p in scanned_paths)
    and auto['doc_corpus']['dbt_layer_excluded'] >= 2,
    f"scanned={scanned_paths} excluded={auto['doc_corpus']['dbt_layer_excluded']}"))

# ── 10. Home precision (docs_scan 1.5): a doc HOMES an identifier only in a ──
# definitional context. A bare reference — a fenced-SQL mention, a
# checklist/metadata table cell, a backtick in prose, or an infra-doc
# terminology colon-list — does NOT home it. This is the precision fix that
# shrinks multi_home from a noisy bare-occurrence population to the docs that
# actually compete with dbt for a definition.
H = ds._definitional_homes

# Definitional homes — MUST be detected.
results.append(case(
    "home: heading whose subject is the identifier",
    'fct_orders' in H("## fct_orders\nHow the orders mart is built.", 'readme')))
results.append(case(
    "home: 'The X table' heading still names its subject",
    'dim_customers' in H("### The dim_customers table\n", 'architecture')))
results.append(case(
    "home: column-dictionary row key",
    'order_total' in H("| Column | Description |\n|---|---|\n"
                       "| order_total | total value |\n", 'readme')))
results.append(case(
    "home: '`x` means …' prose definition",
    'fct_revenue' in H("For finance, `fct_revenue` means net revenue.", 'other')))
results.append(case(
    "home: glossary entry in a glossary-typed doc",
    'fct_revenue' in H("- **fct_revenue**: gross revenue including refunds.",
                       'glossary')))

# Bare references — MUST NOT be homes (the real-evidence homonym population).
_sql = ("## Performance\nExample query:\n```sql\nselect credits_used, account_name\n"
        "from warehouse_metering_history\n```\n")
_sql_homes = H(_sql, 'runbook')
results.append(case(
    "bare: a column named only inside fenced SQL is NOT a home",
    'credits_used' not in _sql_homes and 'account_name' not in _sql_homes,
    f"homes={sorted(_sql_homes)}"))
_checklist = ("## New data source\n| Task | Owner |\n|---|---|\n"
              "| Add kpi_status to sheets.yml | you |\n")
results.append(case(
    "bare: a checklist/metadata table cell is NOT a home",
    'kpi_status' not in H(_checklist, 'readme'),
    f"homes={sorted(H(_checklist, 'readme'))}"))
_termlist = ("### Additional development notes\nUseful terminology in the code:\n"
             "- `email`: The email of the user.\n- `username`: The Snowflake username.\n")
_term_homes = H(_termlist, 'readme')
results.append(case(
    "bare: a code-terminology colon-list in a README is NOT a home",
    'email' not in _term_homes and 'username' not in _term_homes,
    f"homes={sorted(_term_homes)}"))
results.append(case(
    "bare: a backtick mention ('a `stage` has to be created') is NOT a home",
    'stage' not in H("When productionalizing, a `stage` has to be created on "
                     "Snowflake.", 'runbook')))
results.append(case(
    "bare: a common word inside a longer heading is NOT a home",
    'email' not in H("## Email configuration settings\n", 'readme')))

# Fixture-level: the same identifier is a home when defined, not when bare-only.
bare = ds.scan(FIXTURE, inventory, doc_sources=['home-precision/bare'], today=TODAY)
bare_mh = {m['identifier'] for m in bare['multi_home_candidates']}
results.append(case(
    "fixture: dbt-pinned dim_customers is NOT multi-home when only bare-referenced",
    'dim_customers' in [d for doc in bare['doc_corpus']['docs']
                        for d in doc['identifier_mentions']]
    and 'dim_customers' not in bare_mh,
    f"candidates={sorted(bare_mh)}"))
real = ds.scan(FIXTURE, inventory, doc_sources=['home-precision/real'], today=TODAY)
real_mh = {m['identifier'] for m in real['multi_home_candidates']}
results.append(case(
    "fixture: dim_customers IS multi-home when a glossary defines it",
    'dim_customers' in real_mh, f"candidates={sorted(real_mh)}"))

print()
failed = sum(1 for r in results if not r)
if failed:
    print(f"FAILED: {failed}/{len(results)}")
    sys.exit(1)
print(f"OK: {len(results)}/{len(results)} passed")
