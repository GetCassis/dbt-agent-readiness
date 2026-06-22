---
name: dbt-agent-readiness
description: |
  Audit a dbt project for agent-readiness: what would an AI agent get wrong if you pointed
  it at this data today? Produces a prioritized report organized by failure modes (wrong numbers,
  wrong table, wrong column, can't join, query fails). Scales via two-pass architecture with
  parallel subagents. Each subagent reads its own phase instruction file, keeping context tight.
  Use when asked to "audit", "agent-readiness", "scan dbt project", "check data quality",
  "how ready is my data for AI agents", or "run dbt-agent-readiness."
argument-hint: "[path/to/dbt/project]"
allowed-tools:
  - Bash
  - Glob
  - Read
  - Grep
  - Write
  - AskUserQuestion
  - Agent
---

# dbt-agent-readiness (orchestrator)

**Target project path:** `$0` (or current directory if not specified)

This file orchestrates the audit. Phase instructions live in `phases/` files. Each subagent reads only its own phase file. The orchestrator passes structured JSON between phases.

## Design principles

The audit is framed around **what an agent actually hits** (code evidence) vs **what an audit can only forecast** (missing tests, unenforced relationships). Findings that require querying the warehouse to confirm (duplicates, orphans, bad data) are not reported as facts.

- **Report split into Blockers vs Hygiene.** Blockers require code evidence (scope divergence, copy-paste descriptions, broken refs, polymorphic columns, within-model collisions, unit mismatch, measure/agg mismatch, high-confidence phantom columns). Hygiene lists missing tests and unenforced relationships, each with a runnable verification query the user can run in ten minutes to confirm or dismiss.
- **Broken refs always Blocker #1.** `issues.broken_refs` is the most evidence-backed possible finding: the query fails at compile time. Exception: when the project declares package or extension deps (`packages.yml` / `dependencies.yml`) that are not installed (`dbt_packages/` absent) and there is no compiled manifest, unresolved refs are package models or user-supplied extension points, not broken refs. They move to `issues.broken_refs_suppressed_no_deps` and synthesis emits one aggregate "run `dbt deps` (then `dbt compile`)" notice instead of per-ref Blockers (`packages_unresolved` is true).
- **Phantom columns suppressed when evidence is weak.** If a model uses `dbt_utils.star`, `SELECT *` that can't be resolved, or Jinja for-loops, and no compiled manifest is present, the phantom finding is not emitted. It goes to `catalogs.phantom_columns_suppressed_no_manifest` instead. Synthesis emits one aggregate "run `dbt compile`" notice rather than per-model `provisional` rows. All rows in `phantom_columns_by_model` carry `confidence: 'high'` and are evidence-backed.
- **Phantom columns traced through multi-hop CTEs and column lineage.** `_extract_columns_via_sqlglot` resolves CTE output columns recursively (depth 10), so a YAML column that survives through `base -> mid -> top` is not flagged phantom. When the simple YAML-vs-SQL diff still flags something, `cross_reference` retries via `sqlglot.lineage.lineage`; resolved findings land in `catalogs.phantom_columns_resolved_by_lineage` rather than `phantom_columns`. Unit / currency drift candidates (`col * 100`, `col / 100.0`, etc.) are collected into `catalogs.potential_unit_drift` for synthesis to treat as Blocker candidates when the description doesn't call out the conversion.
- **`catalogs.description_contradicts_sql`** catches three high-signal failure modes deterministically: copy-paste descriptions, scope contradictions ("toutes les lignes" + non-trivial WHERE), and measure/agg mismatches ("count of customers" + `SUM(...)`).
- **`catalogs.undefined_column_refs`** makes the worst query-fails bug deterministic: for every model, each SELECT scope (outer query + CTEs) is resolved against its input relations (CTEs recursively, ref'd models through their extracted columns); a column referenced in SELECT or GROUP BY that no input produces is flagged with `confidence: 'high'`. Scopes with any unresolvable input (macros, regex-fallback upstreams, sources) are skipped rather than guessed at. Constructs that produce columns no input relation lists are handled so they never read as undefined: SQL date-part tokens inside `DATEADD`/`DATEDIFF`/`DATE_TRUNC` (`day`, `month`, `quarter`...), `UNPIVOT` value/name outputs, lateral table-function system columns (`SPLIT_TO_TABLE` -> `value`), and `fivetran_utils.fill_staging_columns` style macro column sets. A `ref()` always resolves to the model, never a same-named sibling CTE. Without a compiled manifest these checks stay conservative by construction (verified against real Snowflake projects: GitLab, Stripe, Mattermost). **`catalogs.fan_out_joins`** deterministically flags models joined by 2+ downstream models on a key with no uniqueness guarantee, each with a runnable verification query. A guarantee is a column-level `unique` test, the tested PK, or a `dbt_utils.unique_combination_of_columns` tuple (read from inline tests and from YAML anchor aliases). A join on the whole tuple or a superset is not flagged; a join on a strict subset still can fan out and stays flagged.
- **`catalogs.effective_description_coverage`** reports raw vs effective coverage. Effective = raw minus weak / phantom-documented / contradicts-SQL columns. The gap is the share of docs an agent cannot trust.
- **Severity, grain-declared, and zero-tests are not root issues.** Severity gets one line under Hygiene; grain-declared is informational unless the description is also silent on cardinality; zero-tests is appendix-only.
- **"Safe today" criteria.** No Blocker flags, key columns agent-ready, no high-confidence phantoms, either has a PK test OR has 0 inbound refs, not a staging-only alternative to a core model. Grain qualifies via description text ("one row per customer per day") even without `meta.grain:`.

The script-generated review queue drives the flag-driven review group: the Python inventory script extracts SQL snippets (WHERE, CASE WHEN, COALESCE, JOINs), builds a concept index, and generates cross-model flags. The LLM reviews flagged concept neighborhoods rather than importance-scored individual models. Granular catalogs (weak descriptions, convention drift, concept variants, same_name_different_grain, phantom_columns_by_model, enum_value_gaps, seeds_not_tested, unit_variants, unprefixed_booleans, overlapping_concept_columns_within_model, lineage_cycles, yaml_vs_sql_column_count_diff) are consumed by synthesis as appendix tables with exact file paths and column names.

## Routing table

| Project size | Inventory | Flag-driven review | Per-model review | Glossary ask |
|---|---|---|---|---|
| ≤30 models | Script | Inline (no subagents) | Inline (no subagents) | After inventory |
| 31-50 models | Script | 2 parallel subagents | 3 parallel subagents | After inventory |
| 51-200 models | Script | 3-4 parallel subagents | 3-4 parallel subagents | After checkpoint |
| >200 models | Script + user confirm | 4 parallel subagents | 4 parallel subagents | After checkpoint |

## Ground rules

- **Never hallucinate findings.** Every issue must reference a specific file path, model name, and column name you actually read.
- **Never invent model names, column names, or file paths.** Every name must come from a file you read.
- **If unsure, label it "possible issue" with reasoning.** Do not state uncertain findings as fact.
- **Be honest about limitations.** The "What this audit cannot detect" section is mandatory.
- **Exact counts only.** Never use approximate counts (~40%, ~200) in the report. Every metric must be an exact fraction (e.g., 47/118). If you cannot count precisely, say "not assessed" rather than guessing.

## Locate the skill's phase files

The phase instruction files are located relative to this SKILL.md file. Determine the absolute path to this skill's directory, then construct paths like `{skill_dir}/phases/inventory.md`, etc. If the skill is installed at `~/.claude/skills/dbt-agent-readiness/SKILL.md`, then phase files are at `~/.claude/skills/dbt-agent-readiness/phases/inventory.md`.

Use Glob to find the phase files: `**/dbt-agent-readiness/phases/*.md`. Record the base path.

---

## Step 1: Discovery and scoping (inline, ~2 min)

Run this yourself. Do not delegate.

### 1a. Find the dbt project

Find `dbt_project.yml` at the target path. Read it. Extract project name, model paths, vars, and global configs.

**Check for global test severity.** If `data_tests: +severity: warn` is set project-wide, record it under Hygiene as one line ("project severity defaults to `warn`"). Do NOT build a root issue around it -- the team likely knows and may monitor via Elementary, Dagster asset checks, or re_data.

**Jinja-aware severity parsing.** If `+severity:` is a Jinja expression like `{{ env_var('CI_SEVERITY', 'warn') }}`, extract the default argument (`'warn'`) and treat that as the effective default. Note "inferred from env_var default" in the Hygiene line.

### 1b. Build quick file counts

Use Glob (exclude `dbt_packages/`, `target/`):
- `**/*.sql` under model paths → count SQL models
- `**/*.yml` and `**/*.yaml` under model paths → count schema files

### 1c. Classify models by layer

Use directory paths and naming prefixes:
- **Staging:** `staging/` or `stg_` prefix
- **Intermediate:** `intermediate/`, `prep/`, `base/`, or `int_` prefix
- **Core/marts/reference:** `marts/`, `reference/`, `reporting/`, `core/`, `presentation/`
- **Other:** utility, date spines

Layer classification is used for reporting only. It does not drive scoping.

### 1d. Quick ref-count

Use the Grep tool to find all ref() calls across the project:

- Pattern: `ref\(['"][^'"]+['"]\)` with glob `*.sql` under each model path, output_mode `content`
- Parse the matches to count how many times each model name appears as a ref target

If the Grep tool returns too many results, use this Bash one-liner instead:

```bash
python3 -c "
import re; from pathlib import Path; from collections import Counter
c = Counter()
for f in Path('{model_path}').rglob('*.sql'):
    if 'dbt_packages' not in f.parts:
        c.update(re.findall(r\"ref\(['\\\"]([^'\\\"]+)\", f.read_text()))
for m, n in c.most_common(): print(f'{n:4d} {m}')
"
```

Store the result as `pre_ref_counts`. Models with 3+ refs are **priority models** that will get full inventory treatment. Count them: `n_priority`.

### 1e. Check for previous audit

Check if `{project_path}/dbt-agent-readiness.md` exists. If it does, read it and store its contents as `previous_audit`. This will be used in Step 6 to produce a "Changes since last audit" section.

### 1f. Present discovery and ask about glossary

> I found **{project_name}** ({n} models, {n} schema files). **{n_priority} models** have 3+ inbound refs and will be analyzed in depth.
>
> Do you have a **business glossary** (a .md or .csv file with term definitions)? This helps me check naming vs vocabulary.
>
> Reply with the file path, or "no" to proceed with just the dbt project.

### 1f-bis. Determine docs mode (optional, default OFF)

The audit is **dbt-only by default.** An optional docs-scan capability maps the
documentation that lives *outside* the dbt layer (repo `docs/`, runbooks,
READMEs, a dropped `.md`, or a user-pointed source) and reports where context
duplicates, drifts from the code, goes stale, or points off-repo.

Set `docs_mode = true` only when the user opts in — any of:
- the invocation/request mentions docs/documentation ("include docs", "with
  docs", "scan the docs", "docs mode", `--with-docs`), OR
- the user provides a doc source path in reply to the glossary ask.

If `docs_mode` is on and the user named doc sources, store them as
`doc_sources`. Otherwise `doc_sources` stays empty (auto-discover). When
`docs_mode` is false, skip Step 2d and the docs subagent entirely; the rest of
the audit runs unchanged. Do NOT enable docs mode on your own initiative.

### 1g. Determine scope

| Size | Behavior |
|---|---|
| ≤50 models | Full scan, auto-proceed |
| 51-200 | Scan all, deep inventory on priority models only. User can override at checkpoint. |
| >200 | Same as 51-200, but require explicit confirmation before starting. |

### 1h. Early checkpoint for large projects (>100 models only)

**This checkpoint fires based on the dispatch plan, not on whether
inventory was cached.** Even if an inventory JSON already exists on disk,
you still present this estimate and wait for user confirmation before
spawning any deep-pass subagent -- the cost being gated is the LLM dispatch,
not the inventory rebuild.

For projects with >100 models, present an estimate before starting inventory:

> I found **{project_name}** with **{n} models**. Based on ref counts, **{n_priority} models** are priority targets.
>
> **Estimated audit time:** ~{estimate} min
> - Inventory: ~{inv_est} min (scan all models + deep analysis on {n_priority} priority models)
> - Deep pass: ~{dp_est} min (parallel subagents on flagged concepts + priority models)
> - Synthesis: ~5 min
>
> Proceed?

**Estimation formulas:**
- Inventory (script path, Step 2a): `~max(0.25, total_models / 2000)` min. The
  deterministic script parses ~600 models in well under a minute (measured:
  ~19s for 635 models on BigQuery). Only the LLM-fallback path (Step 2b) is
  slow; if you must fall back, use `8 + 0.03 * total_models + 0.4 * n_priority`.
- Deep pass: `max(8, min(15, n_priority * 0.4))` min — this and synthesis are
  the real cost, not inventory.
- Synthesis: 5 min
- Total: sum + 2 min buffer

The dominant cost is the deep-pass LLM fan-out, not inventory. Frame the
estimate that way; do not quote a large inventory time for the script path.

Wait for user confirmation before proceeding.

---

## Step 2: Build inventory

### 2a. Run the deterministic inventory script (preferred)

Run via Bash:

```bash
python3 {skill_dir}/scripts/inventory.py {project_path}
```

Capture the JSON output. If it succeeds (exit code 0, no `"error"` key in output), parse it as the canonical inventory. The script produces:
- All existing inventory data (models, columns, sources, relationships, issues, test_summary)
- `sql_snippets` on each model (WHERE, CASE WHEN, COALESCE, JOINs, etc.)
- `concept_index` (models grouped by shared business concepts)
- `review_queue` (up to 60 flagged risk hypotheses)
- `manifest_used` (true if target/manifest.json contained compiled_code)
- `manifest_present_without_compile` (true when a manifest exists -- typically from `dbt parse` -- but no compiled_code is available; surface this as a Hygiene bullet telling the user that running `dbt compile` would upgrade phantom-column confidence and resolve Jinja-generated columns)
- `packages_unresolved` (true when `packages.yml` / `dependencies.yml` is present but deps are not installed and no compiled manifest exists; `packages_unresolved_ref_count` unresolved refs were moved to `issues.broken_refs_suppressed_no_deps` instead of being reported as broken)

**Skip directly to Step 3b** (importance scoring) -- the script handles all cross-referencing and merge logic.

If the script fails (pyyaml missing, path error, parse error), print the error and fall back to Step 2b.

### 2b. Fallback: LLM inventory subagent

#### For ≤50 models: single subagent

Spawn ONE subagent:

> Read `{skill_dir}/phases/inventory.md` and execute the instructions.
> Target project: `{project_path}`
> Model paths: `{model_paths}`
> Models by layer: {layer_classification_from_step_1}
> Global configs: {severity, vars, etc.}
> Start your response with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences. Just the JSON.

This subagent does ALL deterministic checks and returns a single JSON blob: the canonical inventory.

**Wait for completion before proceeding to Step 3.**

#### For >50 models: parallel scan + deep subagents

Spawn TWO subagents **simultaneously** (in a single message):

#### Inventory-scan subagent (all models, YAML-only)
> Read `{skill_dir}/phases/inventory-scan.md` and execute the instructions.
> Target project: `{project_path}`
> Model paths: `{model_paths}`
> Models by layer: {layer_classification_from_step_1}
> Global configs: {severity, vars, etc.}
> Start your response with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences. Just the JSON.

#### Inventory-deep subagent (priority models only, full depth)
> Read `{skill_dir}/phases/inventory-deep.md` and execute the instructions.
> Target project: `{project_path}`
> Model paths: `{model_paths}`
> Priority models (3+ inbound refs): {list_of_priority_model_names_from_step_1d}
> Global configs: {severity, vars, etc.}
> Start your response with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences. Just the JSON.

**Wait for BOTH to complete before proceeding to Step 3.**

**Note:** The LLM fallback does NOT produce `concept_index` or `review_queue`. If using the fallback, Step 2c is skipped and the deep pass uses importance-only gating.

### 2c. Run dispatch_prep.py for packets + importance + validation + spot-check

**Skip this step if using LLM fallback inventory (no `review_queue` in output).**

Save the inventory JSON to a temp file, then call `dispatch_prep.py`:

```bash
# Assuming the inventory JSON was captured to /tmp/inventory-{project}.json
python3 {skill_dir}/scripts/dispatch_prep.py /tmp/inventory-{project}.json
```

The script returns a single JSON object with four keys:

- `review_packets`: up to 25 packets grouped by concept, each with evidence
  (descriptions, where_clauses, case_when_blocks, coalesce_exprs), risk
  hypothesis, and the set of models. Use these directly in Step 5 Group 1.
- `importance.scores`: per-model importance scores + reasons for every model.
- `importance.deep_pass_scope`: the subset with importance ≥ 3 (or ≥ 2 if
  fewer than 5 qualify), capped at 50. Use for Step 5 Group 2.
- `validation`: structural invariant checks (matches Step 3c). Each entry
  is `{check, ok, detail}`.
- `spot_check`: deterministic version of Step 3d --
  `catalogs.yaml_vs_sql_column_count_diff` flagged models. Use this
  instead of manually reading 2 high-importance YAMLs.

Store the result as `dispatch_prep` for downstream steps.

**Hard cap:** The script already targets 25 packets max, merging the
remainder into a single "miscellaneous" packet if needed.

### 2d. Docs scan (deterministic, docs mode only)

**Skip this step entirely if `docs_mode` is false.**

Reuse the inventory JSON you already saved (do not re-parse the project). Run:

```bash
python3 {skill_dir}/scripts/docs_scan.py \
  --project-path {project_path} \
  --inventory /tmp/inventory-{project}.json \
  --today {YYYY-MM-DD} \
  {if doc_sources: --doc-sources {space-separated paths/globs}}
```

**Nested dbt projects:** auto-discover (no `--doc-sources`) scans the project
path downward. When the dbt project sits in a subdirectory (`dbt_project.yml` is
below the repo root, e.g. `transform/<project>/` or `warehouse/`), the most
authoritative docs (repo `docs/`, `runbooks/`, top-level READMEs) live *above*
it and would be missed. In that case pass `--doc-sources {repo_root}` (the git
root you found in Step 1) so repo-level documentation is included; the dbt layer
is still excluded by config, so the project's own schema docs are not double
counted. Bump `--max-docs` (e.g. 300) on large repos so nothing is silently
dropped.

`--today` must be stamped by you (the run date), so staleness is reproducible.
The script reuses `inventory.py` for the dbt identifier set and the project
config, derives the dbt-layer boundary from every dbt-configured path plus
`{% docs %}` block detection (so dbt's own docs and in-layer READMEs are never
treated as external prose), then emits a single JSON object. No documentation
prose enters any LLM context here. Capture it to `/tmp/docs-scan-{project}.json`
and store as `docs_scan`.

Key fields:
- `identifier_coverage`: models/source-tables documented in docs vs not (a plain
  ratio, never a score).
- `column_drift`: docs claiming columns a model does not emit. Rows with
  `confidence: high` (model YAML mirrors SQL output) are code-evidenced.
- `multi_home_candidates`: identifiers with more than one home, where a *home*
  is a definitional context (a heading subject, a column-dictionary row, a "`x`
  is/means …" definition, or a glossary entry) — not a bare mention in prose,
  SQL, a checklist table, or an infra/setup doc. Each carries
  `is_dbt_identifier`, `authoritative_dbt_definition`, and `severity_if_differ`
  (the conditional Blocker/Hygiene/context a confirmed `differ` would carry under
  each agent grounding model: `repo_grounded` and `metadata_grounded`) — the
  facts the reliability rule in Step 5b reads.
- `external_pointers`, `staleness_flags`, `doc_corpus`, and `llm_queue` (the
  hard-capped flagged subset for the docs subagent, with `dropped_beyond_cap`).

If the script errors (non-zero, `"error"` key), note "docs scan unavailable" as
one line and continue the dbt-only audit. Docs mode never blocks the audit.

---

## Step 3: Score and verify inventory (inline)

### 3a. Merge (only needed when using fallback LLM inventory with >50 models)

**Skip this step if the inventory script (Step 2a) succeeded.** The script produces a single merged inventory with cross-referencing already done.

If you ran parallel inventory subagents, merge the scan and deep inventories into a single canonical inventory JSON:

1. **Start with the scan inventory** (has all models, but lightweight data).
2. **Overlay deep inventory data:** For each model in the deep inventory, replace the scan entry with the deep entry (which has `column_count_sql`, `grain_declared`, resolved descriptions, phantom columns, copy-paste issues).
3. **Merge `columns` arrays:** Use deep inventory columns for priority models. Use scan inventory columns for all other models.
4. **Merge `sources`**: combine from both, deduplicate by source_name + table_name.
5. **Compute `inbound_refs`** for every model: count how many other models (across BOTH inventories) include it in their `outbound_refs`. Update each model's `inbound_refs` from -1 to the actual count.
6. **Detect broken refs**: for each model's `outbound_refs`, check if the target exists in the merged `models` array (by name). If not, add to `issues.broken_refs`.
7. **Build `relationships`**:
   - `declared`: from relationship tests and semantic entity FKs (from deep inventory).
   - `implicit`: FK columns (`_id` suffix) appearing in models across both inventories without a declared relationship.
8. **Build `test_summary`** from merged columns data: count unique, not_null, relationship, accepted_values, other tests. Count models_with_zero_tests. List categorical_columns_without_accepted_values.
9. **Copy `semantic_layer`, `seeds`, `exposures`** from the deep inventory.
10. **Merge `issues`**: combine from both inventories.
11. **Set `total_models`, `total_schema_files`, `total_sources`** from the merged data.
12. **Set `global_severity_warn` and `has_semantic_layer`** from Step 1 discovery and deep inventory.

### 3b. Consume dispatch_prep results

Step 2c's `dispatch_prep` already contains:

- `importance.scores`: per-model importance scores and reasons, using the
  same formula previously inlined here (`+3` inbound≥3, `+2` exposure,
  `+2` semantic model, `+1` materialised, `+1` leaf, `+1` PK test).
- `importance.deep_pass_scope`: models with importance ≥ 3 (fallback ≥ 2,
  capped at 50).

**The review queue flags, not importance scores, are the primary gate for
which models get cross-model review.** A model with importance=1 that
shares a concept with 4 other models will be reviewed in the flag-driven
pass.

Use `dispatch_prep.importance.deep_pass_scope` wherever subsequent steps
reference "deep pass scope".

### 3c. Consume validation results

Step 2c's `dispatch_prep.validation` contains the structural invariant
checks:

1. `total_models_matches_array`
2. `inbound_refs_resolved`
3. `no_orphan_columns`

If any entry has `ok: false`, surface the `detail` string, note the issue,
and adjust downstream expectations.

**Additional checks the script does not perform** (check manually only if
a subagent later misbehaves): for priority models, `column_count_sql` is
not 0; at least one priority model has `column_count_yaml > 0`.

### 3d. Spot-check (deterministic, from dispatch_prep)

`dispatch_prep.spot_check` returns the
`catalogs.yaml_vs_sql_column_count_diff` list: models where YAML declares
≥ the number of columns that SQL emits (the bug-shaped case). The top 5
are pre-filtered.

- If `n_flagged == 0`: noted as a clean pass.
- If `n_flagged > 0`: include the flagged models in the report's "Phantom
  columns" appendix (cross-reference with `catalogs.phantom_columns_by_model`).

Do NOT manually read YAML files for spot-check. The deterministic catalog
is authoritative.

---

## Step 4: Checkpoint (inline)

**For ≤50 models:** Skip. Auto-proceed with full scope. Print a one-line note.

**For 51+ models:** Present the importance-ranked list:

> **Inventory complete.** {total_models} models scanned, {n_deep} analyzed in depth.
>
> **Review queue:** {n_packets} review packets from {n_flags} flags across {n_concepts} concepts
> **Per-model scope:** {n} models with importance ≥ 3
>
> **Estimated deep pass time:** ~{est} min for {n_packets} review packets + {n} per-model reviews
>
> Proceed?

Record the user's choice. If the user doesn't respond within the flow, proceed with the computed scope.

---

## Step 5: Deep pass (PARALLEL)

**Subagent threshold:** If `total_models ≤ 30`, run all deep-pass analysis inline (no subagents). Dispatch to parallel subagents only for projects with >30 models.

**Skip any subagent whose phase doesn't apply** (e.g., skip semantic if inventory shows zero semantic models).

**Model routing (cost).** Spawn ALL Group 1 and Group 2 subagents on **Sonnet**
(the mechanical ones — naming, descriptions-rest — can use Haiku). They read a
phase file plus a data slice and emit JSON; they do not need Opus. Keep Opus for
the orchestrator's Step 5b/6 synthesis only. On a large project this is the
single biggest cost lever — a cold Opus run pays Opus rates on every subagent.

**Pass slices as files, not inline, on large projects.** The inventory can be
multiple MB; inlining slices into prompts breaks. Write each subagent's slice to
a temp JSON file and tell the subagent to Read it. **Cap the naming slice:** do
NOT pass all columns — pass only the deterministic naming-drift candidates
(`catalogs.convention_drift`, `same_name_different_grain`, `concept_variants`,
`unprefixed_booleans`) plus the deep-pass-scope columns. Passing every column is
the usual wall-clock bottleneck and largely re-derives those catalogs.

**Output format rule for ALL subagents:** Append this to every subagent prompt:
> Start your response with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences. No commentary. Just the JSON.

### Group 1: Flag-driven review

**Skip if no review_queue in inventory (LLM fallback).** Fall back to Group 2 only.

Distribute review packets across 3-4 parallel subagents. Sort packets by severity (highest first), then round-robin distribute so each subagent gets a mix.

**Subagent count:** `ceil(total_packets / 6)`, minimum 2, maximum 4.

Each subagent receives:

> Read `{skill_dir}/phases/review-packet.md` and execute.
> Project path: `{project_path}`
> Review packets assigned to you:
> ```json
> {packets_json}
> ```
> For each model referenced, here are the file paths:
> {model_name: {sql_path, yaml_path} for each model in packets}
> [append output format rule]

### Group 2: Per-model review

Spawn these subagents **simultaneously** with Group 1:

**Context efficiency:** Each subagent only needs a subset of the inventory. Filter before passing to cut context by 3-5x on large projects. Below, `{inventory.X}` means extract only that section.

#### Subagent A1: Descriptions + Grain (priority top 5)
> Read `{skill_dir}/phases/descriptions-priority.md` and execute.
> Deep pass scope priority: {top_5_models_by_importance_from_deep_pass_scope}
> Inventory (models): {inventory.models -- only the top-5 priority models}
> Inventory (columns): {inventory.columns -- only columns for the top-5 priority models}
> Inventory (semantic_layer): {inventory.semantic_layer -- if exists}
> [append output format rule]

#### Subagent A2: Descriptions (remaining scope, capped)
> Read `{skill_dir}/phases/descriptions-rest.md` and execute.
> Deep pass scope rest: {deep_pass_scope_minus_top_5}
> Inventory (models): {inventory.models -- only models in deep_pass_scope_rest, name/layer/description_text/grain fields}
> Inventory (columns): {inventory.columns -- only columns for deep_pass_scope_rest}
> [append output format rule]

Dispatch A1 and A2 in parallel with the other Group 2 subagents. Merge their
`description_findings` and `model_summaries` in synthesis; only A1 produces
`grain_findings` and `fan_out_risks`.

#### Subagent B: Naming
> Read `{skill_dir}/phases/naming.md` and execute.
> Deep pass scope: {models_in_scope_with_importance_scores}
> Inventory (columns): {inventory.columns -- ALL columns, not just deep pass scope; naming needs cross-layer view}
> Inventory (models): {inventory.models -- name, layer, grain_declared, grain_statement only}
> [append output format rule]

#### Subagent C: Joins
> Read `{skill_dir}/phases/joins.md` and execute.
> Deep pass scope: {models_in_scope_with_importance_scores}
> Inventory (models): {inventory.models -- name, layer, sql_path, inbound_refs, outbound_refs, has_pk_test, pk_column, materialization}
> Inventory (relationships): {inventory.relationships}
> Inventory (exposures): {inventory.exposures}
> [append output format rule]

#### Subagent D: Semantic layer (skip if no semantic models)
> Read `{skill_dir}/phases/semantic.md` and execute.
> Deep pass scope: {models_in_scope_with_importance_scores}
> Inventory (semantic_layer): {inventory.semantic_layer -- full}
> Inventory (models): {inventory.models -- only models referenced by semantic models, with sql_path and outbound_refs}
> Inventory (relationships): {inventory.relationships}
> [append output format rule]

#### Subagent E: Business terms

Canonical-term analysis: recurring business terms (revenue, savings, installations, active, etc.) that are defined inconsistently across models, plus enum gaps and seed-connection gaps that the deterministic catalogs in `inventory.catalogs.enum_value_gaps` and `inventory.catalogs.seeds_not_tested` can hint at but not fully explain (e.g., whether two definitions are actually business-equivalent requires domain reasoning).

Pass a focused slice, not the whole inventory -- keeps the subagent cheap:

> Read `{skill_dir}/phases/business-terms.md` and execute.
> Deep pass scope: {models_in_scope_with_importance_scores}
> Inventory (columns): {inventory.columns -- columns in deep_pass_scope + any column whose name stem matches a concept in concept_index with ≥3 models}
> Inventory (concept_index): {inventory.concept_index -- top 20 concepts by model count}
> Inventory (seeds): {inventory.seeds -- full}
> Inventory (catalogs.enum_value_gaps): {pass full -- it's small}
> Inventory (catalogs.seeds_not_tested): {pass full}
> Inventory (semantic_layer): {inventory.semantic_layer -- if exists}
> Inventory (models): {inventory.models -- name, layer, description_text, sql_snippets.where_clauses[:1], sql_snippets.case_when_blocks[:2] for models in scope}
> {if glossary was provided: Glossary path: {absolute_path_to_glossary_file} -- read it yourself with the Read tool}
> [append output format rule]

#### Subagent F: Docs (docs mode only -- skip if `docs_mode` is false or if `docs_scan.llm_pass.recommended` is false)

**Gate.** The deterministic scan decides whether this pass is worth running.
`docs_scan.llm_pass.recommended` is now gated on **actionable** signals only:
high-confidence column drift, a no-fallback multi-home contradiction, or doc
column-claims to verify. A dictionary that simply agrees with the dbt layer is
reported under `llm_pass.context_signals` (so it still appears in the docs map)
but does NOT trigger the pass, because there is nothing for the LLM to
adjudicate. Skip Subagent F entirely when `recommended == false`. When you skip,
still emit the docs map (coverage, staleness, external pointers, generated-doc
count, doc classification, and `context_signals`) and note `llm_pass.reasons` in
the report. The scan's `llm_queue.multi_home` carries the no-fallback candidates
only; do not send the dbt-pinned ones
(`dropped_beyond_cap.multi_home_hygiene_only_not_sent`) to the subagent. They are
not dropped, and they are not auto-Hygiene: Step 5b adjudicates them inline from
the snippets on each `multi_home_candidate`, because a dbt-pinned `differ` is a
Blocker for a repo-grounded agent (Hygiene only for a metadata-grounded one).
Holding them off the subagent keeps its cost proportional; the inline pass runs
in synthesis, which already holds the scan JSON. This inline pass runs whether or
not Subagent F ran, so a repo whose only docs signal is dbt-pinned multi-home
(gate `recommended == false`) still surfaces its repo-grounded Blockers.

Light adjudication of the flagged rows the deterministic scan produced. This
subagent sees only short snippets, never whole docs, and never follows links.

> Read `{skill_dir}/phases/docs.md` and execute.
> LLM queue from the docs scan:
> ```json
> {docs_scan.llm_queue}
> ```
> [append output format rule]

Cost is bounded by the number of flagged rows (tens), independent of doc volume.
Merge its `multi_home_verdicts`, `doc_column_verdicts`, and `doc_classifications`
in synthesis.

**Wait for all Group 1 + Group 2 subagents to complete.**

### Subagent result handling

**JSON extraction fallback:** If a subagent's response doesn't start with `{`, extract the first `{...}` JSON block from the response (find the first `{` and the last `}`). Subagents occasionally prepend commentary despite instructions.

**Runtime envelope wrapping.** When collecting each subagent result,
wrap it as:

```json
{
  "subagent": "descriptions_priority" | "descriptions_rest" | "naming" | "joins" | "semantic" | "business_terms" | "docs" | "review_packet_{i}",
  "start_ts": "<ISO 8601>",
  "end_ts": "<ISO 8601>",
  "result": { ...the subagent's parsed JSON... }
}
```

Write the capture timestamps yourself when you send and receive the
subagent message. The wrapper makes post-hoc eval cheaper and leaves the
raw result untouched.

**Dedup pass in synthesis.** Before emitting
`description_findings`, reduce on `(model, column)`: keep the first entry,
drop later duplicates. Subagent A can occasionally emit a column twice under
enumeration pressure. This guard is a safety net even with the phase-file
duplicate guards.

**Partial failure:** If a subagent returns invalid JSON or fails entirely, do NOT re-run it. Mark that analysis dimension as "Not assessed" in the report and proceed with available data. A partial report is better than a retry loop.

### Minimum viable audit

The report is **publishable** if the inventory completed AND at least 2 Group 1 subagents + 1 Group 2 subagent returned valid results (or at least 3 Group 2 subagents if Group 1 was skipped).

If fewer succeeded, warn the user: "This audit is incomplete -- only {n} analysis dimensions produced results. Consider re-running." Still produce a partial report with available data, but flag it clearly.

---

## Step 5b: Root-cause synthesis (inline)

Collapse all findings into **Blockers** (code-evidenced, max 6) and **Hygiene** items (forecasts, each paired with a verification query).

### Process

1. **Collect all findings** from:
   - `inventory.issues.broken_refs` -- always Blocker #1 when non-empty.
   - `inventory.catalogs.undefined_column_refs` -- always a Blocker candidate, ranked with broken_refs: the model references a column in SELECT or GROUP BY that no input CTE/ref produces, so the query fails at compile/run time. Every row is deterministic and carries `confidence: 'high'`; cite the row's `sql_path` and `scope`.
   - `inventory.catalogs.description_contradicts_sql` -- each entry is a Blocker candidate (copy-paste, model_scope_contradiction, measure_agg_mismatch).
   - `inventory.catalogs.overlapping_concept_columns_within_model` -- Blocker candidates.
   - `inventory.catalogs.enum_value_gaps.casing_mismatches` -- Blocker candidates only when the drift is *in observed data* (not when one side is yaml-only).
   - `inventory.catalogs.unit_variants` -- Blocker candidates when stems overlap across query-path models.
   - `inventory.catalogs.phantom_columns_by_model` -- Blocker candidates only for rows where `confidence == 'high'`. Provisional rows go to Hygiene.
   - Group 1 packet verdicts (confirmed / partially_confirmed) -- Blocker candidates for scope divergence, polymorphism, same-word-different-definition.
   - Group 2 subagent outputs: description findings, naming findings (casing drift in data), join findings, semantic findings, business-terms findings.
   - `inventory.test_summary` + `inventory.relationships.implicit` -- Hygiene candidates.
   - `inventory.catalogs.fan_out_joins` -- Hygiene candidates: 2+ downstream models join this model on a key with no uniqueness guarantee (no column `unique` test, no tested PK, and no `unique_combination_of_columns` tuple covering the join key). Each row ships its own `verification_query`; emit it verbatim.
   - **(docs mode only)** `docs_scan.column_drift` -- rows with `confidence == 'high'` are Blocker candidates: a doc claims a column the model does not emit, and the model's YAML mirrors its SQL so the absence is real. `provisional` rows go to Hygiene. Cross-reference with Subagent F's `doc_column_verdicts`.
   - **(docs mode only)** `docs_scan.multi_home_candidates`. Two adjudication paths feed this. (a) No-fallback candidates carry Subagent F's `multi_home_verdicts`. (b) dbt-pinned candidates (`authoritative_dbt_definition.exists == true`, which Subagent F never receives) are adjudicated here, inline: read the `sources` snippets on the candidate (the dbt description vs each doc home) and judge `agree` / `differ` / `can_t_tell` yourself, using the same calibration as `phases/docs.md` (only `differ` when you can name the inconsistency in scope, filter, grain, or measure; silence in one home is not disagreement; a bare identifier-name match is `can_t_tell`, not `differ` — a short or common name like `email`, `stage`, `status`, or `mode` appearing in an unrelated context, a different table, an infra or admin runbook, or a generic code-terminology note, is a homonym, so only `differ` when the doc defines the SAME object the dbt layer defines). Bound the inline pass to the top ~15 candidates by `doc_count`; if more remain, report the count under the boundary note instead of adjudicating all. For any candidate whose verdict (from either path) is `differ`, apply the reliability rule (step 2) to classify it. `agree` / `can_t_tell` verdicts are dropped.
   - **(docs mode only)** `docs_scan.identifier_coverage`, `docs_scan.external_pointers`, `docs_scan.staleness_flags`, `docs_scan.doc_corpus` -- context/Hygiene candidates (coverage gaps, off-repo authority, stale docs, where context lives).

2. **Classify each finding as Blocker or Hygiene.**

   A finding is a **Blocker** only if one of these is true:
   - A broken `ref()` exists (`issues.broken_refs`).
   - An undefined column reference exists (`catalogs.undefined_column_refs`) -- same rank as broken refs; the SQL cannot build.
   - The description demonstrably contradicts the SQL (copy-paste, scope, agg mismatch).
   - Two+ models give different SQL answers to the same conceptual question (packet verdict with confirmed severity).
   - A column is polymorphic across models (`entity_id`, `state`, etc.).
   - Within-model concept collision (`catalogs.overlapping_concept_columns_within_model`).
   - Unit drift (EUR/EUR cents, Wh/kWh) on overlapping query paths.
   - Casing drift observed in actual data (both variants appear in the column).
   - High-confidence phantom column (confidence==high).
   - Deprecated column still exposed in a mart.
   - **(docs mode)** Doc-vs-code drift: `docs_scan.column_drift` row with `confidence == 'high'` (doc claims a column the model does not emit). Code-evidenced.
   - **(docs mode)** A confirmed multi-home `differ` contradiction, classified by **agent grounding model** (state the assumption in the report's grounding-model note). Severity is conditional, not single-archetype. Read `severity_if_differ` on the candidate, which pre-computes both; label the finding with both severities rather than forcing one:
     - **repo-grounded** (the realistic default): a coding or RAG agent handed the whole repo (Claude Code, Cursor, repo-RAG) reads the dbt project AND `docs/` AND READMEs, sees both sides of the contradiction, and has no rule for which wins. A `differ` is a **Blocker** here whenever the term is a dbt identifier (`is_dbt_identifier == true`), whether or not dbt pins it.
     - **metadata-grounded** (the conservative subset): an agent that queries the dbt layer only. A `differ` is a **Blocker** here only when nothing pins the term (`is_dbt_identifier == true` AND `authoritative_dbt_definition.exists == false`); when dbt pins it, that agent answers from the dbt layer, so it is **Hygiene** for this archetype.
     So a no-fallback `differ` is a Blocker for both; a dbt-pinned `differ` is a Blocker for repo-grounded, Hygiene for metadata-grounded. Cite the two conflicting snippets either way.

   A finding is **Hygiene** if it's a forecast whose realization the audit can't confirm without querying the warehouse:
   - Missing `unique` / `not_null` / `relationships` / `accepted_values` tests.
   - Undeclared grain when the description is silent on cardinality.
   - Suppressed phantom findings (`catalogs.phantom_columns_suppressed_no_manifest` non-empty). Model uses macros and no compiled manifest is present; re-run with `dbt compile` to resolve.
   - Project-wide `+severity: warn` default.
   - Models with zero tests (use `test_summary.models_with_zero_tests_list` for the names).
   - Fan-out joins (`catalogs.fan_out_joins`): the join exists and the unique test is missing, but whether duplicates actually occur needs the row's `verification_query` run against the warehouse.
   - **(docs mode)** A dbt-pinned multi-home `differ` contradiction (`authoritative_dbt_definition.exists == true`) is Hygiene **only for a metadata-grounded agent**: that agent answers from the dbt layer, so the conflicting prose is stale duplication, not an answer-breaker. For a repo-grounded agent the same finding is a Blocker (see the Blocker rule above). Carry both labels.
   - **(docs mode)** `provisional` `column_drift` rows (model's column set only partially known).
   - **(docs mode)** Off-repo authority (`external_pointers`: Google Docs, Confluence, Notion, Slack the agent cannot read), stale docs (`staleness_flags`), and coverage gaps (`identifier_coverage` undocumented list). These are context/Hygiene: they map where context lives and what an agent cannot see, not a code failure.
   - **(docs mode)** A `differ` contradiction on a term that is NOT a dbt identifier (`is_dbt_identifier == false`): context only, for both archetypes -- neither agent queries it as a dbt object.

3. **Cluster Blockers by root cause** (max 6):
   - "Same-word-different-definition across models"
   - "Descriptions contradict SQL"
   - "Polymorphic keys / overloaded columns"
   - "Unit / currency drift"
   - "Within-model concept collision"
   - "Broken refs / undefined column references" (always #1 when present)
   - "Bilingual description corpus" (when >20% non-English)

4. **For each Blocker (max 6), produce:**
   ```json
   {
       "title": "Revenue is defined 3 ways across finance and growth",
       "failure_scenario": "Agent asked 'what was Q1 revenue?' returns different numbers depending on which model it routes to",
       "evidence": "Cite a specific file path + line/fragment OR catalog row reference (e.g., catalogs.description_contradicts_sql[3]). Must be observable in the code.",
       "affected_models": ["model_a", "model_b", "model_c"],
       "blast_radius": "which teams/questions this affects",
       "remediation": "Create canonical dim_revenue_definitions or add explicit scope to each model's description",
       "fix_type": "doc_only|naming_only|test_only|model_refactor|semantic_layer_decision|governance",
       "effort": "afternoon|few_days|sprint|structural"
   }
   ```

5. **For each Hygiene item, produce a verification query** (runnable against the warehouse) so the reader can turn the forecast into a ten-minute check:
   - Missing PK test → `SELECT {pk_col}, COUNT(*) FROM {model} GROUP BY 1 HAVING COUNT(*) > 1`
   - Missing relationship → `SELECT COUNT(*) FROM {from_model} a LEFT JOIN {to_model} b ON a.{fk}=b.{pk} WHERE b.{pk} IS NULL AND a.{fk} IS NOT NULL`
   - Missing not_null → `SELECT COUNT(*) FROM {model} WHERE {col} IS NULL`
   - Missing accepted_values → `SELECT DISTINCT {col} FROM {model}` (compare to description/glossary)
   - Suppressed phantoms (`phantom_columns_suppressed_no_manifest`) → one aggregate Hygiene bullet: "Run `dbt compile` and re-audit. N models with macro-generated column lists (`dbt_utils.star`, unresolved `SELECT *`, Jinja for-loops) had phantom findings suppressed because the static YAML-vs-SQL diff can't be trusted there. A compiled manifest resolves them." List up to 5 affected models; do not emit per-model phantom rows for these.
   - `manifest_present_without_compile=True` → same aggregate bullet, with wording noting the manifest exists but lacks `compiled_code` (typically from `dbt parse`). Example wording: "Run `dbt compile` (not just `dbt parse`) to produce a manifest with `compiled_code`."
   - `packages_unresolved=True` (`issues.broken_refs_suppressed_no_deps` non-empty) → one aggregate Hygiene bullet: "Run `dbt deps` and re-audit. N refs resolve to package models or user-supplied extension points that are not installed, so broken-ref detection was suppressed rather than reported as Blockers. Install deps (and `dbt compile`) for reliable broken-ref and column detection." Do not emit per-ref Blockers for these.

6. **Generate readiness verdict** (one of):
   - **Ready for limited pilot** -- no Blockers, safe perimeter exists
   - **Not ready for self-serve** -- Blockers exist but a safe starting perimeter is viable
   - **Unsafe for business-critical Q&A** -- fundamental Blockers prevent safe use

7. **Define safe starting perimeter:**
   - **Safe today:** models that meet ALL of:
     - No Blocker flags touching this model (no confirmed review-packet verdicts, no description_contradicts_sql entry for this model, no high-confidence phantom columns, no overlapping_concept_columns hit, no unit drift, no broken ref target)
     - Description clarifies grain (either `meta.grain:` set OR description contains "one row per X" / "unique on X" / "grain:")
     - Key columns (PK + FKs + measures) are agent-ready per Group 2 descriptions verdict
     - Either has a `unique` PK test, OR `inbound_refs == 0` (no downstream fan-out risk)
     - Not a staging-only model when a core alternative exists (concept_index overlap)
   - **Safe after one small fix:** models that would qualify after a single change -- adding a `Scope:` line, adding a `unique` test, disambiguating two date columns, wiring a column description. Lead the per-model row with the specific fix.
   - Never mix "safe today" with "safe after one small fix" in the same table.

8. **Generate remediation backlog:**
   - This week: doc/naming fixes (quick wins)
   - This sprint: model + test changes
   - Later: structural changes

### Root issue rules

- Maximum 6 Blockers. Cluster aggressively -- don't list three variants of "descriptions contradict SQL" as separate Blockers.
- Each Blocker must cite evidence: a file path, a catalog row, or a packet verdict. "Docs could be better" is not a Blocker. "`target` measure description says 'Distinct count of customers placing orders' but semantic model uses `agg: sum` on a dollar column (see catalogs.description_contradicts_sql)" is.
- If a finding doesn't have code evidence and doesn't map to a runnable verification query, demote it to the appendix.
- **Severity / grain_declared / zero-tests** never drive a Blocker. They may appear in Hygiene or the appendix; never in Top Risks narrative.

---

## Step 6: Synthesize and write report (inline)

Read `{skill_dir}/report-template.md` for the output structure.

**Emit granular catalogs as appendix sections.** The inventory's `catalogs` object
provides pre-computed, citable reference data. Do NOT paraphrase or summarize
these into root issues -- include them as dedicated appendix subsections so an
engineer remediating the audit has exact names and paths.

Catalogs to surface when non-empty:
- `catalogs.missing_column_descriptions` → "Columns without descriptions" table
- `catalogs.weak_column_descriptions` → "Low-quality column descriptions" table
- `catalogs.missing_model_descriptions` → in the coverage snapshot
- `catalogs.convention_drift.temporal_suffix_mix` → "Temporal suffix convention" section
- `catalogs.convention_drift.boolean_prefix_mix` → "Boolean prefix convention" section
- `catalogs.convention_drift.mart_prefix_mix` → "Mart prefix convention" section
- `catalogs.concept_variants` → "Same-concept-different-name clusters" section
  (each cluster is backed by `evidence` -- the actual `X as Y` alias pairs and
  the models they were observed in; cite those, never paraphrase)
- `catalogs.same_name_different_grain` → "Same name, different grain" section
- `catalogs.phantom_columns_by_model` → "Phantom columns (YAML not in SQL)"
  appendix table with one row per model, listing the exact columns. Do NOT just
  cite the total count -- the per-model list is the single most actionable
  artifact for remediation.
- `catalogs.enum_value_gaps.undocumented_values` → "Undocumented enum values"
  table (column × documented_values × values seen in SQL but not in test)
- `catalogs.enum_value_gaps.casing_mismatches` → "Enum value casing drift"
  table (column × normalized-form × concrete variants across models).
  Each variant carries a `source` of `yaml`, `sql`, or `description` --
  include this in the table so drifts that live only in a description can
  be audited at a glance.
- `catalogs.enum_value_gaps.no_source_categorical` → "Categorical columns
  with values only in SQL" table (column × models × observed values)
- `catalogs.seeds_not_tested` → "Seeds defining canonical values not
  referenced in any test" table (seed × rows × columns)
- `catalogs.unit_variants` → "Unit/currency suffix drift" table (stem ×
  suffixes × examples)
- `catalogs.unprefixed_booleans` → addendum under boolean_prefix_mix
  (columns that should probably be prefixed `is_`/`has_`)
- `catalogs.overlapping_concept_columns_within_model` → "Same-concept
  columns inside one model" table (model × core-stem × variant column names).
  Flags e.g. `deployment_start_date` vs `zone_deployment_start_date`.
- `catalogs.lineage_cycles` → "Lineage cycles" section (empty when the
  project has none; cite cycles as `a → b → c → a`). Zero hits is a valid
  pass, not a skip.
- `catalogs.yaml_vs_sql_column_count_diff` → cross-reference with the
  phantom_columns_by_model table. If a model appears here and in
  phantom_columns_by_model, lead with the specific phantom list.
- `catalogs.description_contradicts_sql` → "Per-model description
  contradictions" section in the report. Split by `kind`: copy_paste,
  model_scope_contradiction, measure_agg_mismatch. Each entry is a Blocker
  candidate and must be evaluated during synthesis.
- `catalogs.undefined_column_refs` → "Undefined column references" appendix
  table (model × column × clauses × scope × input relations). Every row is
  also a Blocker candidate ranked with broken_refs -- surface it in both
  places.
- `catalogs.fan_out_joins` → "Fan-out joins without a unique key test"
  table under the Hygiene appendix (model × join column × downstream
  models × verification query).
- `catalogs.effective_description_coverage` → Coverage snapshot metric.
  Emit BOTH raw and effective percentages side-by-side. Effective = raw
  minus columns in weak / contradicts_sql / phantom_documented. The gap is
  the share of docs an agent cannot trust.
- `catalogs.phantom_columns_by_model` → each row carries a
  `confidence` field. Only `high`-confidence rows are eligible for Blocker
  status. `provisional` rows (model uses macros) go to Hygiene with
  "re-run with `dbt compile`" as the verification step. Surface the
  `macro_signals` field in the report table so the reader can see why a
  row is provisional (`select_star`, `dbt_utils.star`, `jinja_for_loop`).

Root issues should reference catalogs when relevant ("see Appendix: phantom
columns"), not duplicate them inline.

**Docs mode only.** When `docs_mode` is on, add the "Context beyond the dbt layer
(docs scan)" section from `report-template.md`, fed by `docs_scan`, Subagent F's
verdicts (no-fallback candidates), and your inline verdicts (dbt-pinned
candidates): where context lives (doc count, classified), coverage gaps (exact
documented/undocumented lists), duplicated homes (multi-home `differ` verdicts
with both snippets, classified by the conditional reliability rule), off-repo
authority (counts + hosts), and staleness. State the **agent grounding model**
note from `report-template.md` so the report declares its assumption: repo-grounded
is the realistic default, metadata-grounded the conservative subset. Promote
high-confidence `column_drift` into the Blockers section; promote every dbt-identifier
`differ` contradiction (no-fallback and dbt-pinned) into Blockers for a repo-grounded
agent, and label the dbt-pinned ones Hygiene for a metadata-grounded agent.
Include the boundary note verbatim: the scan maps where context lives and where
it duplicates or points away; it does not fully read prose to adjudicate every
definition. Surface the caps and `dropped_beyond_cap` so nothing reads as
complete coverage when it was sampled.

### 6a. Calibrate tone

If the project is well-maintained (high coverage, consistent naming, strong tests), lead with what's done well. Don't make a clean project sound broken.

### 6b. Collect all results

Merge root issues from Step 5b with per-model findings from Group 2. Deduplicate any overlapping findings.

### 6c. Apply risk adjustment

If semantic layer exists (Subagent D results):
- Entity FKs reduce "can't join" risk
- Described measures reduce "wrong numbers" risk
- Undescribed measures INCREASE "wrong numbers" risk (false confidence)
- Note adjustments explicitly

### 6d. Compare against previous audit (if exists)

If `previous_audit` was stored in Step 1e, compare the current findings against it:
- Which findings are **new** (not in previous audit)?
- Which findings are **resolved** (in previous audit but no longer present)?
- Which findings **persist** (still present)?

Add a "Changes since last audit" section to the report with a brief summary. Keep it short: 3-5 bullet points.

### 6e. Write the report

Write to `{project_path}/dbt-agent-readiness.md` using the structure from `report-template.md`. Include `Inventory method: script` (or `LLM subagent (fallback)`) in audit metadata. When phantom-column rows with `confidence: provisional` exist, note "YAML + raw SQL (manifest not compiled)" in the header. If Write fails, output the full report in the conversation. Never error out.

### 6f. Present summary

Show the user:
- The readiness verdict
- Top 3 root issues
- Safe starting perimeter (if any)
- Path to the full report

Do not dump the full report into the conversation.

### 6g. Cleanup

Delete any temporary files created during the audit:
- `{project_path}/inventory.json` or similar inventory dump files
- `/tmp/inventory-*.json` files
- `/tmp/docs-scan-*.json` files (docs mode)
- Any other intermediate files written during subagent execution
