# Changelog

All notable changes to the dbt-agent-readiness skill.

## 1.6.1 (2026-06-22)

Precision follow-up to the 1.6.0 conditional-severity rework. 1.6.0 routes
dbt-pinned multi-home contradictions to adjudication (repo-grounded Blocker vs
metadata-grounded Hygiene); validation on the 13 public blog repos showed that
population was 618 candidates but almost entirely noise. The old `home` heuristic
counted a bare identifier-name occurrence as a definitional home — a column in a
runbook SQL query, a README file-format table, an onboarding checklist — and
short names produced false homonyms (cagov matched `account_name` / `schema_name`
/ `credits_used` against Snowflake admin SQL; gitlab `stage` against a "Snowflake
stage object" runbook note; `email` / `username` against a code-terminology
README list). Adjudicating 257 of the 618 found zero genuine docs-vs-dbt
contradictions.

- **A doc HOMES an identifier only in a definitional context (docs_scan.py).**
  `_is_doc_home` (a bare-token match against backticks, any table cell, or any
  fenced-code token) is replaced by `_definitional_homes`, which counts a home
  only when the doc DEFINES the term: the identifier is a heading's subject
  (`## fct_orders`), a column-dictionary row key, the subject of a "`x`
  is/means/represents …" prose definition, or a glossary entry. The glossary case
  is counted only in a glossary-typed doc — a colon-list bullet like `- email: …`
  in a README is code terminology, not a data home. Fenced code is stripped
  first, so a query selecting a column or a setup snippet exporting a variable is
  a *use*, never a home. A bare mention in prose, a backtick, or a
  checklist/metadata table cell no longer homes the identifier.
- **Population shrunk from noise to signal.** Across the 13 blog repos, total
  multi_home candidates dropped 633 → 116 and the dbt-pinned population that
  1.6.0 routes to adjudication dropped 618 → 116 (−82%); the no-fallback
  (Blocker-eligible, LLM-queue) population dropped 15 → 0. Per-repo (before →
  after): gitlab 41→4, cal-itp 82→4, tuva 250→37, stripe 90→0, full-funnel
  61→43, ga4 25→17, salesforce 21→0, snowplow 19→10, gtm-analytics 17→0, cagov
  11→0, jaffle_corp 8→0, jaffle_shop 7→0, mattermost 1→1. Every survivor
  inspected is a genuine definitional home — a column-dictionary table, a
  model-overview README table, or a metrics table — not a bare reference.
- **docs_scan bumped to 1.5.** The output shape is unchanged; only which mentions
  carry `home: true` changed, so `multi_home_candidates`, the LLM queue, and the
  `dropped_beyond_cap` counts all narrow to the high-signal set. Identifier
  coverage, column drift, external pointers, and staleness are computed from
  mentions (not homes) and are unaffected.

Pairs with 1.6.0: that change routes dbt-pinned multi-home to adjudication; this
change makes that routed population small and high-signal. The two are intended
to ship to the public repo together as one consolidated release.

Test suite 114 → 126 (12 home-precision assertions in `tests/test_docs_scan.py`
asserting that a fenced-SQL mention, a checklist-table cell, a code-terminology
colon-list, and a bare backtick are NOT homes while a heading subject,
column-dictionary row, prose definition, and glossary entry are; plus planted
`test-fixtures/docs-context/home-precision/` fixtures). The public repo is
untouched.

## 1.6.0 (2026-06-22)

Reliability rule reworked from a single archetype to **conditional severity by
agent grounding model**. The docs-vs-dbt multi-home contradiction rule used to
demote any dbt-pinned `differ` to Hygiene with the reasoning "the agent answers
from dbt." That assumed a metadata-grounded agent. It under-reported for the
common case: a repo-grounded agent (a coding or RAG agent handed the whole repo,
Claude Code / Cursor / repo-RAG) reads the dbt project AND `docs/` AND READMEs,
sees both sides of the contradiction, and has no rule for which wins.

- **Two archetypes, both labeled (SKILL.md Step 5b, report-template.md).** A
  docs-vs-dbt `differ` on a dbt identifier is now:
  - **dbt-pinned** (`authoritative_dbt_definition.exists == true`): Blocker for a
    repo-grounded agent, Hygiene for a metadata-grounded agent. Was: Hygiene
    only.
  - **no-fallback** (`exists == false`): Blocker for both. Unchanged.
  - **not a dbt identifier**: context for both. Unchanged.
  Findings carry both labels; the report no longer forces one. Repo-grounded is
  the realistic default, metadata-grounded the conservative subset.
- **Agent grounding model note (report-template.md).** Every report now declares
  its assumption in a note under the readiness verdict, so the reader knows which
  archetype a severity is read for.
- **dbt-pinned candidates adjudicated inline (SKILL.md Step 5b, phases/docs.md).**
  The scan's LLM queue and gate are unchanged: Subagent F still receives only the
  no-fallback candidates, holding its cost proportional. The dbt-pinned ones,
  which it never received, are now adjudicated inline in synthesis from the
  snippets already on each `multi_home_candidate` (bounded to the top ~15 by doc
  count; the rest reported under the boundary note). This inline pass runs whether
  or not Subagent F ran, so a repo whose only docs signal is dbt-pinned multi-home
  still surfaces its repo-grounded Blockers.
- **docs_scan bumped to 1.4.** Each `multi_home_candidate` now carries a derived
  `severity_if_differ` map (`repo_grounded` / `metadata_grounded`) packaging the
  conditional severity for synthesis to read. Additive only; the queue, gate, and
  `dropped_beyond_cap` semantics are unchanged.
- **Language.** Replaced "the agent answers from dbt" / "an agent grounded on dbt
  metadata" with "a metadata-grounded agent," and named the repo-grounded
  archetype explicitly throughout SKILL.md, report-template.md, and
  phases/docs.md.

Test suite 111 -> 114 (three `severity_if_differ` assertions in
`tests/test_docs_scan.py`). The public repo is untouched.

## 1.5.0 (2026-06-20)

Accuracy fixes from the tuva docs-mode validation run (1,182-model healthcare
package) plus the full-funnel docs-mode run. docs_scan bumped to 1.3. Test suite
79 -> 111 (new `tests/test_v12_fixes.py` + `tests/test_docs_scan_v13.py`).

From the full-funnel run (docs_scan 1.3):

- **Generic key/value tables mis-read as column claims (docs_scan.py).**
  Column-claim extraction now mines only column-dictionary tables (header signals
  `column`/`field` or `type`/`description`); a generic `| Property | Value |` or
  `| Setting | Value |` metadata table under a model heading no longer leaks its
  header word as a claimed column, and a table header row is never itself emitted
  as a column. On full-funnel this dropped a phantom `property` column broadcast
  onto ~29 models: `column_drift` 51 -> 7, doc-column LLM queue 40 -> 7, all bogus
  `property` claims gone.
- **Inconsistent doc paths + duplicate-content double counting (docs_scan.py).**
  All doc paths are now cited under one base (the smallest dir containing the
  project anchor and every scanned doc), so a doc inside the dbt project is no
  longer cited as a bare `README.md`. Byte-identical docs are deduped (recorded
  in `doc_corpus.duplicate_content`) so their identifiers, claims, and pointers
  are counted once. On full-funnel this caught 12 duplicate docs (triplicated
  command files + an architecture doc copied to two locations); scanned 34 -> 22.
- **Semantic-layer metrics/measures not recognized as authoritative (docs_scan.py).**
  `_build_identifier_facts` read a `description` key off the inventory's semantic
  metric/measure dicts, but the inventory carries the boolean under
  `has_description`. Every described MetricFlow metric therefore looked undefined
  (`auth_dbt=False`), so a prose-vs-metrics contradiction (e.g. CLAUDE.md defining
  Session CVR as `conversions/sessions` while the canonical metric is
  `total_orders/total_sessions`) was escalated to a Blocker instead of Hygiene. A
  described metric/measure is now an authoritative dbt home, so such contradictions
  are Hygiene (stale prose duplication) per the reliability rule. On full-funnel
  this moved 14 described metrics out of the no-fallback queue: Blocker-eligible
  multi-home 20 -> 6 (the 6 are raw source tables defined only in docs, correctly
  still Blocker-eligible).

From the tuva run (docs_scan 1.2):

- **Phantom-column false positives on Jinja column captures (inventory.py).**
  `_detect_macro_column_generation` now recognizes `{%- set cols -%} ...
  {%- endset -%}` capture blocks (expanded as `{{ cols }}`) and custom
  column-spreading macros (`*_columns(...)`, e.g. `select_extension_columns`).
  Models built this way are macro-generated and their phantom findings are
  suppressed (not emitted as high-confidence) when no compiled manifest is
  present. On tuva this moved the flagship core models (`core__medical_claim`
  66 cols, `core__encounter` 47, `core__eligibility` 37, `core__pharmacy_claim`
  32) out of the high-confidence phantom catalog: 65 -> 45 models, 847 -> 529
  columns. Effective description coverage now counts only high-confidence
  phantoms, so macro-suppressed models no longer deflate it (tuva 71.2% ->
  81.4%).
- **`measure_agg_mismatch` SUM-of-flag false positives (inventory.py).** A
  `SUM(CASE WHEN ... THEN 1 ...)` or `SUM(<flag>)` IS a count, so it is no
  longer flagged as "description says COUNT, SQL uses SUM". A genuine
  `SUM(<measure>)` against a count-claiming description still flags.
- **`model_scope_contradiction` disclosed-filter false positives
  (inventory.py).** If the WHERE column appears in the model description (the
  filter is disclosed, e.g. "...all rows where disqualified_encounter_flag =
  0"), it is no longer flagged as a hidden scope contradiction.
- **Doc classifier tightened (docs_scan.py).** License / contributor /
  agent-guide files and blog/news posts are never classified as
  glossary/architecture, and head matches are restricted to the title region.
  Stops generic prose words ("definitions", "data model") from inflating the
  gate. On tuva, dictionary/architecture/runbook docs 35 -> 28 with zero
  license/blog/agent files left misclassified.
- **`llm_pass.recommended` gated on actionable signals (docs_scan.py).**
  `recommended` is now true only when there is something to adjudicate
  (high-confidence column drift, a no-fallback multi-home contradiction, or doc
  column-claims). Dictionary-docs-present and defers-authority-offsite move to
  the new `llm_pass.context_signals` (still reported, not a trigger). Resolves
  the prior contradiction where `recommended=true` coexisted with an empty
  queue. SKILL.md Subagent F gate updated to match.
- **Manifest-generated docs detected (docs_scan.py).** Docs that render tables
  from the dbt manifest at build time (Docusaurus `JsonDataTable`, `jsonPath=`,
  "generated by dbt") are flagged in a new top-level `generated_docs` summary
  and per-doc `generated_from_manifest`; column-claim extraction is skipped for
  them (they cannot drift). On tuva, 68 such docs detected — explaining the
  honest `column_drift = 0`.
- **Nested-repo doc auto-discovery (docs_scan.py).** When the dbt project is
  nested under a conventional data-layer subdir (`warehouse/`, `transform/`,
  `projects/`, ...) below the git root and no `--doc-sources` is given,
  discovery now expands to the repo root so repo-level docs ABOVE the dbt layer
  are not missed. Guarded so a dbt project buried under `test-fixtures/` in an
  unrelated repo does not trigger expansion. `doc_corpus` now reports
  `discovery_root` and `nested_dbt_project`.

## 1.4.0 (2026-06-20)

Optional docs-scan mode. The audit can now map the documentation that lives
*outside* the dbt layer (repo `docs/`, runbooks, READMEs, or a user-pointed
source) and report where context duplicates, drifts from the code, goes stale,
or points off-repo. **dbt-only remains the default;** docs mode is opt-in and the
skill runs unchanged on a bare dbt project.

- New `scripts/docs_scan.py` (deterministic, near-zero tokens). Reuses
  `inventory.py` for the dbt identifier set and project config, and accepts the
  inventory JSON already built in Step 2a (`--inventory`) so the project is not
  re-parsed. Emits: `identifier_coverage` (models/source-tables documented vs
  not, a plain ratio), `column_drift` (docs claiming columns a model does not
  emit; `high` confidence when the model's YAML mirrors its SQL output),
  `multi_home_candidates` (identifiers with more than one home),
  `external_pointers` (off-repo authority by host), `staleness_flags`, the
  `doc_corpus`, and a hard-capped `llm_queue` for the light LLM pass.
- The dbt-layer boundary is derived from every dbt-configured path
  (`model-paths`, `docs-paths`, `analysis-paths`, `macro-paths`, `seed-paths`,
  `snapshot-paths`, `test-paths`) plus `{% docs %}` block detection, so dbt's
  own doc-block files and in-layer READMEs are never mis-flagged as external
  prose.
- New `phases/docs.md` (light LLM, default-on within docs mode): adjudicates
  agree/differ on multi-home snippets, matches/drift on doc column claims, and
  refines doc classification. It sees only short snippets -- never whole docs,
  never followed links. Cost scales with flagged rows (tens), not doc volume.
- **Severity follows agent-answer reliability, not evidence provenance.** A
  confirmed multi-home contradiction is a Blocker only when the agent has no
  authoritative source to fall back on (the term is a dbt identifier AND the dbt
  layer carries no good definition for it). When the dbt layer pins the term, the
  conflicting prose is stale duplication -- Hygiene, not a Blocker. Doc-vs-code
  drift at `high` confidence is always a Blocker (code-evidenced). `docs_scan.py`
  attaches `is_dbt_identifier` and `authoritative_dbt_definition` to every
  candidate so synthesis decides this deterministically.
- SKILL.md wired: docs-mode opt-in (Step 1f-bis), `docs_scan.py` run (Step 2d),
  the docs subagent (Subagent F), Blocker/Hygiene collection with the reliability
  rule (Step 5b), and the report fold (Step 6). report-template.md gains the
  "Context beyond the dbt layer (docs scan)" section with an explicit boundary
  note. Caps and dropped-beyond-cap counts are surfaced; nothing reads as full
  coverage when it was sampled.
- **Phantom false-positive fix (Jinja for-loops + compiled manifest).** Column
  extraction upgraded SQL *snippets* to the manifest's `compiled_code` but still
  derived the column set from raw Jinja-stripped SQL. A for-loop body like
  `{{ pm }}_amount` strips to a single `_amount` token, so the real generated
  columns were flagged high-confidence phantom even though the manifest resolved
  them, and the for-loop suppression was bypassed because a manifest was present.
  Columns are now re-extracted from `compiled_code` when available. Verified on
  `jaffle_shop_duckdb`: `orders` phantom count 4 to 0 (the payment-method
  amounts are real), effective coverage corrects from 52.4% to 71.4%, and the
  genuine `customers.total_order_amount` phantom still fires. New regression
  fixture `test-fixtures/manifest-forloop/` + `scripts/tests/test_phantom_manifest.py`.
- New committed regression gate `test-fixtures/docs-context/` +
  `scripts/tests/test_docs_scan.py` (20 assertions): pins the coverage gap,
  high-confidence doc-vs-code drift (and no false drift on a correct doc),
  both multi-home cases (no-fallback Blocker vs pinned Hygiene), off-repo
  pointers, staleness, and the dbt-layer boundary exclusion. The LLM agree/differ
  verdict is out of scope for the deterministic gate by design.

## 1.3.0 (2026-06-12)

`fan_out_joins` no longer flags a join whose key set is already covered by a model-level uniqueness guarantee.

Before this release the check only recognized a column-level `unique` test. A model that declares uniqueness on a column tuple through `dbt_utils.unique_combination_of_columns` was still flagged, even when downstream models joined it on the whole tuple. Tuples attached through a YAML anchor alias (`data_tests: *anchor`) were missed for the same reason: model-level tests were never read.

- Model-level `data_tests` / `tests` are now parsed. `dbt_utils.unique_combination_of_columns` (and the older `unique_combination`) tuples are read from both the classic `combination_of_columns:` form and the newer `arguments: combination_of_columns:` form. YAML anchors and aliases are expanded by the loader, so an anchored test is read the same as an inline one.
- A join key is suppressed only when every join clause that uses it covers a uniqueness guarantee on the joined model: a column-level `unique` test or the tested PK among the clause keys, or a unique-combination tuple that is a subset of the clause keys. A join on the whole tuple (or a superset) cannot fan out and is not flagged. A join on a strict subset of the tuple still can, so it stays flagged.

Verified on three public projects: Cal-ITP `fan_out_joins` 6 to 2. Two daily-summary facts that carry a `(dt, base64_url)` tuple test via a YAML anchor stop firing, while the genuine `organization_dataset_map` fan-out, whose tuple test does not cover its join key, still fires. Mattermost (6) and GitLab (26) are unchanged, so no real fan-out is suppressed. New regression fixture `test-fixtures/fan-out-joins/` and `scripts/tests/test_fan_out_joins.py` pin tuple coverage, the anchor-alias case, the subset-still-fires case, and a no-test fan-out guard.

## 1.2.0 (2026-06-11)

Reliability fixes for the two deterministic query-fail checks (`undefined_column_refs`, `broken_refs`) on real Snowflake and package-heavy projects. A source-only run (no compiled manifest) used to emit whole classes of false positive at `confidence: high`. Those classes are now suppressed by construction.

`undefined_column_refs`:

- SQL date-part keywords inside `DATEADD`, `DATEDIFF`, `TIMEADD`, and `DATE_TRUNC` (`day`, `month`, `quarter`, `week`, `hour`, `minute`, and the rest) are unit tokens, not column references. They are never flagged.
- `UNPIVOT(value FOR name IN (...))` value and name outputs are recognized as produced columns.
- Lateral table functions (`SPLIT_TO_TABLE`, `FLATTEN`) expose system output columns (`value`, `index`, `seq`, ...) that are no longer read as undefined.
- `fivetran_utils.fill_staging_columns`, `get_columns_in_relation`, and `apply_source_relation` are treated as macro-generated column sets. Without a compiled manifest the model is skipped, the same way `dbt_utils.star` already was.
- A `ref()` resolves to its model, never a sibling CTE of the same name. A Jinja-stripped expression in a CTE select list now marks that CTE's shape unresolvable, so downstream scopes are skipped rather than checked against a placeholder column.

`broken_refs`:

- When `packages.yml` or `dependencies.yml` is declared but the dependencies are not installed (`dbt_packages/` absent) and no compiled manifest exists, unresolved refs are package models or user-supplied extension points, not broken refs. They move to `issues.broken_refs_suppressed_no_deps` and synthesis emits one aggregate "run `dbt deps`" notice. New output fields `packages_unresolved` and `packages_unresolved_ref_count`.

Verified on eight public projects: GitLab `undefined_column_refs` 31 to 0 and `broken_refs` 4 to 0, Stripe 218 to 0, Tuva `broken_refs` 327 to 0, with the genuine `messy-jaffle-shop` `has_refund` query-fail still firing. New regression fixture `test-fixtures/sql-edge-cases/` and `scripts/tests/test_undefined_column_refs.py` pin every blind spot.

## 1.1.0 (2026-06-09)

Three checks that previously relied on LLM judgment during the deep pass are now computed deterministically by the inventory script.

- New `catalogs.undefined_column_refs`: per model, every SELECT scope (outer query and each CTE) is resolved against its input relations (CTEs recursively to depth 10, ref'd models through their extracted column lists); any column referenced in SELECT or GROUP BY that no input produces is flagged with `confidence: 'high'`. Always a Blocker candidate, ranked with broken refs. Conservative by construction: scopes are skipped when any input is unresolvable (macro-generated columns without a compiled manifest, regex-fallback extractions such as incremental-model tails, sources, subqueries). Local CTEs now correctly shadow same-named models during resolution.
- New `catalogs.fan_out_joins`: models joined by 2+ downstream models on a key with no `unique` test. Join targets are resolved directly or through grain-preserving passthrough CTEs; each row carries the join column, downstream models, a sample ON condition, and a runnable verification query. Hygiene candidate in synthesis.
- Fixed `test_summary.models_with_zero_tests` undercount: models with no YAML entry at all were not counted (messy-jaffle-shop reported 3, truth is 6). The summary now also enumerates the models in `models_with_zero_tests_list`.
- SKILL.md Step 5b and report-template.md wired for both new catalogs (Blocker collection, Hygiene verification queries, appendix tables).

## 1.0.0 (2026-04-20)

Initial public release.

- Evidence-based report split: **Blockers** (code-level failures an agent will hit today) and **Hygiene** (risk factors shipped with runnable verification queries).
- Deterministic Python inventory with 15+ catalogs: phantom columns, concept variants, unit drift, description-vs-SQL contradictions, overlapping-concept-columns, lineage cycles, enum value gaps, same-name-different-grain, convention drift, and more.
- Dialect-aware SQL parsing via [sqlglot](https://github.com/tobymao/sqlglot): BigQuery, Snowflake, DuckDB, Redshift, Postgres. Recursive CTE column resolution and column-level lineage for phantom-column detection.
- Two-pass subagent architecture that scales to project size: inline (≤30 models), 2-4 parallel subagents (31-500 models), checkpoint before dispatch (>500 models).
- Manifest-aware phantom detection: when `target/manifest.json` is present, macros (`dbt_utils.star`, `SELECT *`, Jinja for-loops) are resolved. When absent, phantom findings on macro-using models are suppressed rather than emitted as noise.
- dbt mesh support: two-arg `ref('project', 'model')` recognized; cross-project refs excluded from broken-ref checks.
- Doc block resolution (`{% docs %}` / `{{ doc() }}`) and Jinja-aware severity parsing.
- Safe-pilot perimeter: each audit ends with an explicit list of models agents can query safely today and a remediation backlog.
