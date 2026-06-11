# Changelog

All notable changes to the dbt-agent-readiness skill.

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
