# Synthesis (orchestrator, inline)

The orchestrator reads this file at Step 5b and applies it itself, with every subagent result and the inventory JSON in hand. It is not dispatched to a subagent.

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

## Report emission

Use this list when writing the report at Step 6 with [report-template.md](../report-template.md).

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
  Each row carries a `confidence` field. Only `high`-confidence rows are
  eligible for Blocker status. `provisional` rows (model uses macros) go to
  Hygiene with "re-run with `dbt compile`" as the verification step. Surface
  the `macro_signals` field in the table so the reader can see why a row is
  provisional (`select_star`, `dbt_utils.star`, `jinja_for_loop`).
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

Root issues should reference catalogs when relevant ("see Appendix: phantom
columns"), not duplicate them inline.

**Docs mode only.** When `docs_mode` is on, add the "Context beyond the dbt layer
(docs scan)" section from [report-template.md](../report-template.md), fed by `docs_scan`,
Subagent F's verdicts (no-fallback candidates), and your inline verdicts (dbt-pinned
candidates): where context lives (doc count, classified), coverage gaps (exact
documented/undocumented lists), duplicated homes (multi-home `differ` verdicts with
both snippets, classified by the agent grounding model rule in Process step 2),
off-repo authority (counts + hosts), and staleness. State the grounding-model note
from the template so the report declares its assumption. Promote high-confidence
`column_drift` and the `differ` contradictions into Blockers exactly as Process step 2
classifies them. Include the boundary note verbatim: the scan maps where context lives
and where it duplicates or points away; it does not fully read prose to adjudicate
every definition. Surface the caps and `dropped_beyond_cap` so nothing reads as
complete coverage when it was sampled.
