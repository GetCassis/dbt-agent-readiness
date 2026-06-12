# Descriptions and grain phase

Assess description quality and grain declarations for models in the deep pass scope. This is judgment-based work: could an agent use each column correctly based only on its description?

## Input

You receive:
- `deep_pass_scope`: list of model names to assess
- `inventory_json`: the canonical inventory from the inventory phase

Use the inventory to find file paths. Read YAML and SQL files directly for detailed assessment.

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this JSON structure:

```json
{
  "model_summaries": [
    {
      "model": "model_name",
      "total_columns_assessed": 12,
      "agent_ready_count": 8,
      "not_agent_ready_count": 4
    }
  ],

  "description_findings": [
    {
      "model": "model_name",
      "column": "column_name",
      "column_type": "measure|categorical|fk|date",
      "current_description": "string or null",
      "agent_ready": false,
      "gap": "what specifically is missing, e.g. 'doesn't specify whether refunds are deducted'"
    }
  ],

  "grain_findings": [
    {
      "model": "model_name",
      "grain_declared": true,
      "grain_statement": "One row per order",
      "grain_source": "models: description|semantic_model description|doc() block|not found",
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

### Description agent-readiness assessment

For each model in scope, read its YAML (and doc blocks if descriptions use `{{ doc() }}`). Assess each column by type:

**Measures** (columns with amount, count, sum, total, rate, revenue, cost, price, quantity, average in name):
- Does the description specify what's included and excluded? (gross vs net, with/without tax, before/after refunds)
- Does it specify the unit or currency if applicable?
- Flag as not agent-ready if an agent could plausibly compute the wrong number.

**Categorical columns** (named status, type, category, tier, method, mode, state, level, kind):
- Does the description list valid values, or reference where to find them?
- Flag as not agent-ready if an agent writing a WHERE clause would have to guess values.

**Foreign keys** (_id columns that appear in other models per the inventory):
- Does the description say which entity or model this key points to?
- Flag as not agent-ready if an agent couldn't determine the join target.

**Date/time columns in fact/core models** (columns with _at, _date, _timestamp suffixes):
- Does the description clarify which event the timestamp captures?
- Flag as not agent-ready only if two date columns in the same model could be confused.

**Calibration:** Only flag descriptions where missing info could lead to a wrong answer. "Total revenue from completed orders" is agent-ready even without currency. "The total amount" is not.

**Enumeration rule:** For each model in scope that has a YAML entry, enumerate every column assessed in the `description_findings` array with its `agent_ready` verdict. The synthesis step needs per-column data to compute exact counts (e.g., "47/118 key columns agent-ready"). Never use approximate counts (~40%). Every number must be derivable from the array.

**Scope control for large projects:** If the deep pass scope has >30 models, enumerate all columns for the top 15 models by importance score. For the remaining models, enumerate only columns that are NOT agent-ready (skip agent-ready columns to save tokens). Always include a summary count per model: `{"model": "model_name", "total_assessed": 12, "agent_ready": 8, "not_agent_ready": 4}`.

### Grain analysis

For every model in scope:

1. Check model description for explicit grain ("one row per", "one record per", "one entry per", "grain:", "each record represents", "unique on")
2. Check semantic model description if one exists
3. Check doc() blocks if referenced
4. If no grain found: analyze SQL for likely grain (GROUP BY, primary key pattern in final SELECT)
5. Check if grain is enforced by a `unique` or `unique_combination_of_columns` test

**Risk assessment:**
- **High:** core/reference model with no grain declared and 2+ inbound refs
- **Medium:** core/reference model with no grain declared but ≤1 inbound refs, or grain in semantic model but not in models: block
- **Low:** staging/intermediate model or model with 0 inbound refs

### Fan-out detection

For models in scope, use inventory data to detect fan-out risk (no SQL reading needed):
- For each model, check its `outbound_refs`. For each referenced model, check inventory: does it have `has_pk_test: true`?
- If not, any join to that model could cause row multiplication
- Higher risk when: the joining model is a fact/core table, the referenced model has 2+ inbound refs, and the referenced model lacks a PK test
- Also check doc blocks (from inventory descriptions) for explicit fan-out warnings
