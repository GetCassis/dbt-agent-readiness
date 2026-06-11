# Descriptions phase — A1 (priority models)

This phase does not enumerate every column to score "agent-ready / not ready" — deterministic catalogs already catch missing descriptions, placeholder text, and short restatements. Your job is the part heuristics miss: **descriptions that contradict the SQL** or **semantic copy-paste errors that look fine length-wise**.

Grain analysis + fan-out risk stay here (they lean on the top models and need human judgement).

## Input

You receive:
- `deep_pass_scope_priority`: the top 5 models in the deep pass scope, by importance score
- `inventory_json`: the canonical inventory
- `catalogs.description_contradicts_sql`: a starter list of deterministic contradictions already caught. You should **validate these** and **find additional cases the regex-based catalog missed** — semantic-layer measures, multi-column misalignment, stale descriptions that refer to deprecated logic, etc.

Use the inventory to find file paths. Read YAML and SQL files directly for detailed assessment.

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary.

Return EXACTLY this JSON structure:

```json
{
  "model_summaries": [
    {
      "model": "model_name",
      "columns_with_contradictions": 2,
      "columns_agent_ready": 10,
      "columns_not_ready_but_fixable": 4
    }
  ],

  "description_contradictions": [
    {
      "model": "model_name",
      "column": "column_name_or_null_for_model_level",
      "kind": "copy_paste|scope|agg_mismatch|stale_reference|self_contradiction|unit_missing_on_measure",
      "description_says": "quoted snippet from description",
      "sql_does": "quoted snippet from SQL or semantic model",
      "agent_failure": "one sentence on what the agent will get wrong"
    }
  ],

  "description_findings": [
    {
      "model": "model_name",
      "column": "column_name",
      "column_type": "measure|categorical|fk|date|other",
      "current_description": "string or null",
      "agent_ready": false,
      "gap": "what specifically is missing — only populate for columns NOT in description_contradictions; focus on ambiguities a verification query couldn't catch"
    }
  ],

  "grain_findings": [
    {
      "model": "model_name",
      "grain_declared": true,
      "grain_statement": "One row per order",
      "grain_source": "models: description|semantic_model description|doc() block|not found",
      "grain_clear_from_description": true,
      "likely_grain_from_sql": "string or null (only if grain_declared is false)",
      "enforced_by_test": true,
      "risk": "high|medium|low"
    }
  ],

  "fan_out_risks": [
    {
      "model": "model_name",
      "join_column": "column_name",
      "joined_model": "model_name",
      "unique_test_exists": false,
      "description": "what would go wrong"
    }
  ]
}
```

## Instructions

### Priority #1: description contradictions

For each priority model, read YAML + SQL + any doc() blocks and semantic model measures. For each column with a description, ask: **does the description match what the SQL / semantic model actually does?**

Contradiction kinds to look for:

- **copy_paste**: the description is identical (or near-identical) to another column in the same model, but the columns hold different things. Example: `customer_count` and `target` both described as "Distinct count of customers placing orders" — but `target` is a `SUM` of a dollar column.
- **scope**: the description claims totality ("all rows", "every", "toutes les lignes", "entire set", "comprehensive") but the SQL has a non-trivial WHERE clause. Example: `mrt_global__offer` description calls it "comprehensive" while SQL filters `offer_validation='APPROVED' AND venue_id IS NOT NULL`.
- **agg_mismatch**: description says COUNT/SUM/AVG but SQL uses a different aggregation. Check semantic-layer measures too — the deterministic catalog only checks SQL `AGG(...) as col`; a semantic model with `agg: sum` and a description that says "count" is also agg_mismatch.
- **stale_reference**: description mentions values, columns, tables, or logic that no longer exist in the SQL (e.g., "includes CANCELLED and DELIVERED" when SQL only emits DELIVERED).
- **self_contradiction**: the description contradicts itself or the SQL within one sentence ("Total amount for the booking for one quantity" — is it total or unit?).
- **unit_missing_on_measure**: measure column without unit/currency AND the column participates in cross-model revenue/energy arithmetic where unit drift is a real risk (EUR/EUR cents, Wh/kWh, seconds/milliseconds). Only flag when the project has evidence of unit drift elsewhere (e.g., `catalogs.unit_variants` non-empty OR another model uses a different unit suffix).

**Validate the deterministic catalog.** Start with `catalogs.description_contradicts_sql`. For each entry concerning a priority model, confirm the finding is real and either retain or discard it (discarded entries should still appear — mark them `kind: copy_paste` with `agent_failure: "DISCARD — {reason}"` so synthesis knows to drop). Then look for additional contradictions the regex missed.

**Output scoping:** the `description_contradictions` array is the most load-bearing output. Be thorough here. Be terse elsewhere.

### Priority #2: grain

For each priority model:

1. Is the grain **knowable to an agent**? Two passing checks:
   - Explicit `meta.grain:` key, OR
   - Description contains "one row per X" / "unique on X" / "grain:" / "each record represents" / "one record per"
2. Is the grain enforced by a `unique` or `unique_combination_of_columns` test?
3. Set `grain_clear_from_description: true` when (1) passes even without `meta.grain:`. The safe-today check only promotes a model to Hygiene if the description is *also* silent.

Risk:
- **High:** core/ref, 2+ inbound refs, grain unknowable to the agent, no uniqueness test
- **Medium:** core/ref, 0-1 inbound refs OR grain clear from description but no uniqueness test
- **Low:** staging/intermediate OR grain declared AND tested

### Priority #3: fan-out risk

For each priority model's `outbound_refs`, check if the target has `has_pk_test: true`. If not, flag. Include any doc-block warnings about fan-out.

### Priority #4 (residual): description findings for the remainder

Only enumerate columns here that:
- Are NOT already captured in `description_contradictions`
- Have an ambiguity a runtime verification query couldn't trivially catch (e.g., "which of several date columns does 'date' refer to?", "does this measure include refunds?")

Don't produce `description_findings` rows for every column. If the description is clearly agent-ready, skip it. Synthesis can compute counts from `model_summaries`.

**Calibration:** `target = "Distinct count of customers placing orders"` with `agg: sum` is a `description_contradictions` entry (kind=copy_paste + agg_mismatch). `total_revenue = "Total revenue from completed orders"` with no currency is not a contradiction — it's a description gap, goes in `description_findings` with `gap: "no currency stated"`.

**Duplicate guard:** `(model, column)` appears at most once in `description_contradictions` and at most once in `description_findings`. If a column has both a contradiction and a gap, put it only in `description_contradictions`.

**Enumeration rule:** `model_summaries` has one entry per priority model with exact counts. `columns_with_contradictions` + `columns_agent_ready` + `columns_not_ready_but_fixable` = total_columns_assessed.
