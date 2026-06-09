# Report template

Use this structure for the final audit report. Replace all `{placeholders}` with actual values from the inventory, review packet verdicts, and per-model subagent results.

Top risks are split into **Blockers (agent will hit this)** and **Hygiene (risk factors, verify before trusting)**. Blockers require *code evidence* — scope divergence, polymorphic values, description-vs-SQL contradictions, broken refs, unit mismatch, within-model concept collision. Hygiene covers missing tests, unenforced relationships, undeclared grain — these predict agent failure only if the underlying data has problems, which a static audit can't confirm.

---

```markdown
# dbt-agent-readiness: {project_name}

**Scanned:** {total_models} models | **Date:** {date}
{if manifest: **Source:** manifest.json (compiled SQL)}
{if NOT manifest AND any macro_signals observed: **Source:** YAML + raw SQL (manifest not compiled — phantom-column findings flagged provisional)}

## Readiness verdict

**Posture:** {ready for limited pilot / not ready for self-serve / unsafe for business-critical Q&A}
**Distance to ready:** {afternoon of fixes / a few days / one sprint / multi-sprint}
**Confidence:** {high / medium / low} {if low: — explain why}

**In plain terms:** {2-3 sentence summary. What would go wrong today. What's the path to ready.}

## Blockers (agent will hit these today)

Each entry is backed by code evidence: SQL, YAML, or a description that demonstrably contradicts the SQL. An agent querying the project today will produce wrong answers or fail.

{3-6 root issues. Lead with the highest-blast-radius evidence-backed finding. If `issues.broken_refs` is non-empty, it is ALWAYS Blocker #1.}

### 1. {Root issue title — e.g., "Revenue is defined 4 ways across finance and growth"}

**What the agent gets wrong:** {One concrete failure scenario in plain language}
**Evidence:** {File path + line + quoted SQL/YAML fragment OR catalog reference (e.g., `catalogs.description_contradicts_sql[3]`). Must be observable, not inferred.}
**Affected models:** {list, with the key columns}
**Blast radius:** {which questions/teams/domains this affects}
**Fix:** {specific action, not generic}
**Fix type:** {doc_only / naming / test / model_refactor / semantic_layer_decision / governance}
**Effort:** {afternoon / few days / sprint / structural}

{Repeat for each Blocker}

### Eligibility for Blocker status

A finding is a Blocker only if ONE of these is true in the code:

- **Broken ref** in `issues.broken_refs` — query fails at compile time.
- **Scope divergence**: model description promises totality (`all`, `every`, `toutes les lignes`) but SQL has a non-trivial WHERE clause. Caught by `catalogs.description_contradicts_sql` (kind=`model_scope_contradiction`) and review-packet `hidden_filter` verdicts.
- **Same-concept different-definition** across models (booking, revenue, installation, savings). Caught by Group 1 review packets.
- **Polymorphic column** (e.g., `entity_id` holding RTE entity in some rows, scoped housing/device in others). Caught by review packets and `catalogs.same_name_different_grain`.
- **Copy-paste description** (N columns share identical text). From `catalogs.description_contradicts_sql` (kind=`copy_paste`).
- **Measure/agg mismatch** (description says COUNT, SQL uses SUM). From `catalogs.description_contradicts_sql` (kind=`measure_agg_mismatch`).
- **Unit mismatch** (EUR/EUR cents, Wh/kWh) on overlapping columns. From `catalogs.unit_variants` + review-packet evidence.
- **Within-model concept collision** (e.g., `deployment_start_date` + `zone_deployment_start_date`). From `catalogs.overlapping_concept_columns_within_model`.
- **Casing drift in actual data** (`'venueMap'` + `'venuemap'` both present). From `catalogs.enum_value_gaps.casing_mismatches`.
- **Phantom columns** where `confidence == 'high'` (not gated by macro detection). From `catalogs.phantom_columns_by_model`.
- **Deprecated columns still exposed** (glossary marks deprecated; mart still ships them).

If none of the above apply, the finding belongs under Hygiene or Appendix.

## Hygiene (risk factors — verify before trusting the pilot)

These are *forecasts*, not bugs. The audit cannot confirm them without executing queries. Each entry comes with a runnable verification query so you can turn a forecast into a ten-minute check.

### Verification to-do

Run each query against the warehouse. A non-zero result confirms the Hygiene item is an actual Blocker for the pilot; a zero result means you can leave the item for later.

| Risk | Model | Verification query | If non-zero |
|---|---|---|---|
| Potential duplicate PK | `{model}` (inbound_refs={n}) | `SELECT {pk_col}, COUNT(*) FROM {model} GROUP BY 1 HAVING COUNT(*) > 1` | promote to Blocker: fan-out on join silently inflates metrics |
| Potential orphan FK | `{model}.{fk_col}` → `{target_model}` | `SELECT COUNT(*) FROM {model} a LEFT JOIN {target_model} b ON a.{fk_col}=b.{target_pk} WHERE b.{target_pk} IS NULL AND a.{fk_col} IS NOT NULL` | promote to Blocker: INNER JOINs drop rows, LEFT JOINs return nulls agent won't expect |
| Enum drift | `{model}.{col}` (no accepted_values test) | `SELECT DISTINCT {col} FROM {model}` — compare against the values listed in description or glossary | promote if values appear in the data but not in docs |
| Not-null gap | `{model}.{col}` | `SELECT COUNT(*) FROM {model} WHERE {col} IS NULL` | promote if >0 on a column the agent will filter/join on |

{One row per Hygiene item. Leave rows out when the inventory has no evidence of the risk for that model.}

### Standing hygiene items (don't block pilot, keep on backlog)

- **Grain undeclared** on {n}/{total_core} core/reference models. Only promote to Blocker when the description is *also* silent on cardinality — if the description says "one row per customer per day" the agent is fine.
- **Models with zero tests** ({n}/{total}): listed in Appendix.
- **Global test severity:** {project severity — one line}. Only meaningful if the team also has no external monitoring (Elementary, Dagster asset checks, re_data).
- {if inventory.manifest_present_without_compile: **Manifest available but not compiled.** A `target/manifest.json` exists but carries no `compiled_code` — this run is based on raw SQL + YAML. Running `dbt compile` (not just `dbt parse`) resolves Jinja, promotes provisional phantom findings to `high` confidence (or drops them), and exposes macro-generated column lists. Recommended before a second audit.}

## What's safe to start with

### Safe today

Models an agent can query right now with acceptable risk. Each entry meets ALL of:
- No Blocker-eligible flags in review queue
- Description clarifies grain (explicit `meta.grain:` OR "one row per X" in description)
- Key columns have agent-ready descriptions
- No high-confidence phantom columns
- Either has a PK test, OR has 0 inbound refs (pilot can verify fan-out inline)
- Not a staging-only model when a core alternative exists

| Model | Layer | Why safe |
|---|---|---|
| {model} | {layer} | {grain source, description quality, blockers absent} |

### Safe after one small fix

Models that would qualify after a single fix. Lead with the specific fix per row.

| Model | One fix | File |
|---|---|---|
| {model} | {e.g. add Scope: line to description / add `unique` test / disambiguate two date columns} | {yaml_path} |

### Out of scope until remediation

{Question types or concept areas to avoid until Blockers are resolved}

{If no safe models: "No models currently meet all safety criteria. Recommended starting point after remediation: {list}"}

## Remediation backlog

### This week (doc/naming fixes)
- {specific fix + file path}

### This sprint (model + test changes)
- {specific fix + file path}

### Later (structural)
- {specific fix}

## Coverage snapshot

| Dimension | Score | Detail |
|-----------|-------|--------|
| Concept consistency | {good/mixed/poor} | {e.g., 3 fragmented concepts across 12 models} |
| Scope/filter transparency | {good/mixed/poor} | {e.g., 8 models with undocumented filters — observable, not forecast} |
| Description trustworthiness | {good/mixed/poor} | effective coverage {eff}% (raw {raw}%); {n} contradictions |
| Key/entity stability | {good/mixed/poor} | {e.g., entity_id polymorphic in 4 prep models} |
| Safe entry points | {good/mixed/poor} | {e.g., 12 marts clearly classified, 68 ambiguous} |

### Detailed metrics
| Metric | Score |
|--------|-------|
| Models with descriptions | {x}/{n} ({pct}%) |
| Columns with descriptions (raw) | {y}/{m} ({pct}%) |
| Columns with trustworthy descriptions (effective) | {y_eff}/{m} ({pct_eff}%) |
| Key columns agent-ready | {a}/{b} ({pct}%) |
| Description contradicts SQL | {n_contradictions} ({copy_paste} copy-paste, {scope} scope, {agg} agg) |
| Grain declared (core/ref) | {g}/{t} (informational — see Hygiene) |
| Relationships declared / implicit | {r} / {i} (informational — see Verification to-do) |

**Why two coverage numbers?** Raw coverage counts any non-empty YAML description. Effective coverage subtracts columns whose descriptions are weak, copy-pasted, contradict the SQL, or describe phantom columns (documented in YAML but never emitted). The gap between raw and effective is the share of docs an agent cannot trust.

{if strengths: ## What's working well}
{2-4 bullets}

{if previous_audit exists:}
## Changes since last audit
{3-5 bullets: new findings, resolved findings, persistent findings}
{/if}

## Appendix: all findings

### Failure mode risk matrix

| Failure mode | Risk | Key evidence |
|---|---|---|
| Wrong numbers | {level} | {1-line summary, cite catalog or packet} |
| Wrong table | {level} | {1-line summary} |
| Wrong column | {level} | {1-line summary} |
| Can't join | {level} | {1-line summary} |
| Query fails | {level} | {broken_refs count if any; else "compiles cleanly"} |
| Has to guess | {level} | {1-line summary} |

### Language and localization risk
{From naming phase: language mixing findings — if significant (>20% non-English), this is a standalone section}

### Review packet verdicts
{From Group 1: each packet with verdict, evidence, remediation. Confirmed/partially_confirmed only — collapse `not_confirmed` into a single line.}

### Per-model description contradictions
{From catalogs.description_contradicts_sql — split by kind}

**Copy-paste descriptions** ({n})
| Model | Columns sharing one description | Shared text (truncated) |
|---|---|---|
| {model} | `{col1}`, `{col2}` | "{text}" |

**Model scope contradictions** ({n})
| Model | Description claims | SQL filters |
|---|---|---|
| {model} | "{desc snippet — 'all rows' / 'toutes les lignes'}" | `{where_clause}` |

**Measure / aggregation mismatches** ({n})
| Model | Column | Description says | SQL does |
|---|---|---|---|
| {model} | {col} | "{desc snippet}" | `{AGG}(...) as {col}` |

### Catalogs (from inventory.catalogs — emit only non-empty sections)

**Columns without descriptions** ({n} from `catalogs.missing_column_descriptions`)
| Model | Column | Layer |
|---|---|---|
| {model} | {column} | {layer} |

**Low-quality column descriptions** ({n} from `catalogs.weak_column_descriptions`)
| Model | Column | Current text | Reason |
|---|---|---|---|
| {model} | {column} | "{text}" | {placeholder / restates_name / too_short} |

**Temporal suffix convention** (from `catalogs.convention_drift.temporal_suffix_mix`)
Suffixes in use: {_at (n), _date (n), _timestamp (n), ...}. Pick one.
Examples: {examples}

**Boolean prefix convention** (from `catalogs.convention_drift.boolean_prefix_mix`)
Prefixes in use: {is_ (n), has_ (n), ...}. Examples: {examples}
If the project has a dominant convention (≥80% single prefix) and ≥3 columns violate it, elevate to a Blocker (agent filter `WHERE is_X` misses the violators).

**Mart prefix convention** (from `catalogs.convention_drift.mart_prefix_mix`)
Informational — model-naming cosmetics rarely bite the agent.

**Same-concept-different-name clusters** (from `catalogs.concept_variants`)
For each cluster:
- Canonical: {canonical}. Variants: {distinct_names}.
- Evidence from project SQL:
  - `{a} as {b}` observed in `{model}` — {one line per pair}
- Appearances: {list of model.column}

**Same name, different grain** (from `catalogs.same_name_different_grain`)
Columns sharing a name across layers with potentially different grain:
- `{column}` appears in {layers}. Examples: {examples}

**Phantom columns by model** (from `catalogs.phantom_columns_by_model`)
YAML documents columns that the SQL doesn't produce. Each row carries a **confidence** field. `high` = phantom is real; `provisional` = the model uses macros (`dbt_utils.star`, `SELECT *`, Jinja loops) and the static YAML-vs-SQL diff can't be trusted until the user runs `dbt compile` and re-audits.

| Confidence | Model | Count | Phantom columns | Macro signals | YAML path |
|---|---|---|---|---|---|
| high | {model} | {count} | `{col1}`, `{col2}` | — | {yaml_path} |
| provisional | {model} | {count} | `{col1}`, `{col2}` | {e.g. dbt_utils.star, select_star} | {yaml_path} |

Only `high`-confidence phantom findings are eligible for Blocker status. Provisional findings go in Hygiene with "re-run with `dbt compile` to confirm" as the verification step.

**Undefined column references** (from `catalogs.undefined_column_refs`)
Columns referenced in a SELECT list or GROUP BY that no input CTE/ref produces — the query fails at compile/run time. Every row is a Blocker candidate ranked with broken refs; also list it here for remediation.

| Model | Column | Clauses | Scope | Input relations | SQL path |
|---|---|---|---|---|---|
| {model} | `{column}` | {select, group_by} | {cte name / final_select} | {relations} | {sql_path} |

**Description contradicts SQL** (from `catalogs.description_contradicts_sql` — already emitted above, see "Per-model description contradictions")

**Undocumented enum values** (from `catalogs.enum_value_gaps.undocumented_values`)
Columns with an `accepted_values` test whose SQL uses values not in the test.

| Model | Column | Documented | Seen in SQL but not in test |
|---|---|---|---|
| {model} | {column} | {documented_values} | {undocumented_sql_values} |

**Enum value casing drift** (from `catalogs.enum_value_gaps.casing_mismatches`)
Same column name across ≥2 models with values that normalize to the same token but differ in casing/whitespace/hyphens.

| Column | Normalized value | Variants (value → model, source) |
|---|---|---|
| {column} | {normalized} | {value1 ({model1}, {yaml|sql|description})} |

Agent impact: real when the agent joins on the enum value or filters on one specific casing. Less severe than silent wrong-numbers because the failure mode is usually "empty result" which the user notices.

**Categorical columns with values only in SQL** (from `catalogs.enum_value_gaps.no_source_categorical`)

| Column | Models | Values observed in SQL |
|---|---|---|
| {column} | {models} | {sql_values} |

**Seeds defining canonical values not referenced in any test** (from `catalogs.seeds_not_tested`)

| Seed | Rows | Columns | Path |
|---|---|---|---|
| {seed} | {row_count} | {columns} | {path} |

**Unit/currency suffix drift** (from `catalogs.unit_variants`)

| Stem | Group | Suffixes in use | Examples |
|---|---|---|---|
| {stem} | {currency/energy/duration/...} | {suffixes} | {examples} |

**Unprefixed booleans** (from `catalogs.unprefixed_booleans`)

| Model | Column | Signal |
|---|---|---|
| {model} | {column} | {name_pattern / accepted_values} |

**Same-concept columns inside one model** (from `catalogs.overlapping_concept_columns_within_model`)

| Model | Core stem | Variant columns |
|---|---|---|
| {model} | {stem} | {col1}, {col2} |

**Lineage cycles** (from `catalogs.lineage_cycles`) — {0 cycles, clean pass / list cycles as `a → b → c → a`}.

**YAML vs SQL column count diff** (from `catalogs.yaml_vs_sql_column_count_diff`)
Cross-reference with phantom_columns_by_model. Skip if all flagged models appear there.

### Hygiene appendix: test gaps (non-blocking)

**Models with zero tests** ({n}): {comma-separated list from `test_summary.models_with_zero_tests_list`}.

**Fan-out joins without a unique key test** (from `catalogs.fan_out_joins`)
2+ downstream models join this model on a key nothing guarantees is unique — duplicate keys silently multiply joined rows. Run the verification query to turn the forecast into a ten-minute check.

| Model | Join column | Joined by | Verification query |
|---|---|---|---|
| {model} | `{join_column}` | {downstream_models} | `{verification_query}` |

**Missing PK tests on high-ref models**
| Model | Inbound refs | Verification query |
|---|---|---|
| {model} | {n} | `SELECT {pk_col}, COUNT(*) FROM {model} GROUP BY 1 HAVING COUNT(*) > 1` |

**Implicit FK relationships without a `relationships` test** ({n})
Top {k} by blast radius:
| From | To | Verification query |
|---|---|---|
| `{model_a}.{fk_col}` | `{model_b}.{pk_col}` | `SELECT COUNT(*) FROM {model_a} a LEFT JOIN {model_b} b ON a.{fk_col}=b.{pk_col} WHERE b.{pk_col} IS NULL AND a.{fk_col} IS NOT NULL` |

## What this audit cannot detect

- **Runtime data quality** (null rates, freshness, row counts) — requires executing queries. This is why Hygiene items carry verification queries.
- **Source system changes** — only runtime monitoring can detect upstream format changes.
- **Whether a join makes business sense** — can detect structural issues but not domain validity.
- **Query patterns and usage frequency** — requires query log access.
- **Warehouse schema drift** — requires live database access.
- **BI tool metric conflicts** — requires LookML or BI export access.
- **Cross-database joins** — joins spanning multiple databases are not analyzed.
- **Macro-resolved column lists** (`dbt_utils.star()`, `SELECT *`, Jinja loops) — phantom-column findings on these models are marked `provisional`. Running `dbt compile` and re-auditing against `target/manifest.json` resolves them.

## Audit metadata

| Metric | Value |
|--------|-------|
| Total models scanned | {n} |
| Models reviewed by LLM | {n} (via {n} review packets + {n} per-model reviews) |
| Review packets generated | {n} |
| Concept index size | {n} concepts across {n} models |
| Blockers | {n} |
| Hygiene items | {n} |
| Subagents launched | {n} Group 1 + {n} Group 2 |
| Phases completed | {list of completed phases} |
| Inventory method | script {+ manifest.json if used} |

---

*Generated by the [dbt-agent-readiness](https://github.com/GetCassis/dbt-agent-readiness) skill for Claude Code.*
*The problems this audit surfaces are what [Cassis](https://getcassis.com) solves automatically — it builds and maintains your semantic ontology so agents always query the right data.*
```

---

## Notes for the synthesizer

### Blocker vs Hygiene classification

**A finding is a Blocker only with code evidence.** The evidence is one of: broken ref, scope divergence (description-vs-SQL), copy-paste description, measure/agg mismatch, polymorphic column, within-model concept collision, unit mismatch, deprecated-column-still-exposed, casing drift *in observed data*, or a high-confidence phantom column.

**A finding is Hygiene when** it's a forecast that depends on runtime data (missing `unique` test on a PK, missing `relationships` test, missing `not_null`, missing `accepted_values` without observed drift). These get verification queries, not blast-radius language.

**Provisional phantom columns** (`confidence == 'provisional'`) go to Hygiene with "re-run with `dbt compile`" as the verification step.

**Severity and `global_severity_warn`:** drop from the narrative. Keep one line under "Standing hygiene items" noting project severity. Do NOT build a root issue around "tests are advisory" — the team knows, or uses external monitoring the audit can't see.

**`grain_declared` metric:** keep in Coverage snapshot as informational. Only promote to Hygiene for a specific model when *both* `grain_declared=false` AND the description doesn't say "one row per X". Don't make grain a gating criterion for "safe today" by itself.

### Promoting broken refs

If `issues.broken_refs` is non-empty, make it Blocker #1 regardless of other findings. A broken ref means `dbt compile` fails → every agent query that touches the model fails.

### Root issue construction

Each Blocker must have:
1. A concrete failure scenario (not "docs could be better")
2. Specific affected models and columns
3. Evidence quoted from a file (SQL fragment, YAML fragment, catalog row reference)
4. A specific remediation
5. An effort estimate

### Coverage dimensions

The coverage snapshot replaces the earlier flat metric table with 5 qualitative dimensions:
- **Concept consistency**: how many concept stems show divergence (review packets + concept_variants)
- **Scope/filter transparency**: how many models have undocumented WHERE clauses (hidden_filter flags + description_contradicts_sql kind=model_scope_contradiction)
- **Description trustworthiness**: ratio of effective to raw coverage. Good = >90%, mixed = 70-90%, poor = <70%.
- **Key/entity stability**: whether key columns are polymorphic
- **Safe entry points**: how many core/reference models are unambiguous entry points

Score each as good (no flags), mixed (some flags), or poor (many flags or critical issues).

### Tone calibration

Before writing, assess overall health:
- If effective description coverage >80% AND consistent naming AND no Blockers: lead with strengths, findings are "areas for improvement"
- If ANY Blocker is critical or if >3 Blockers: lead with risks regardless of surface coverage
- Never make a clean project sound like it needs major work
- Never bury critical findings in a positive tone

### Key columns agent-ready metric

Denominator: total measure + categorical + FK + date columns in priority models (from descriptions phase)
Numerator: those with agent-ready descriptions (from descriptions phase)

**This MUST be reported as an exact fraction (e.g., 47/118, 40%). Never use ~ or approximate.**

### Report length

Keep the Blockers + Safe perimeter + Remediation backlog + Coverage snapshot under ~100 lines. Hygiene section can be longer (it's reference material). The appendix has no length limit.
