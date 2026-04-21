# Changelog

All notable changes to the dbt-agent-readiness skill.

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
