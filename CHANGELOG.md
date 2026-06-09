# Changelog

All notable changes to the dbt-agent-readiness skill.

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
