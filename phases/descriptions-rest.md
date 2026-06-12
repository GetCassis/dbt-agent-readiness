# Descriptions phase — A2 (remaining scope)

Companion to `descriptions-priority.md`. Handles the deep-pass models outside the top 5. Matches A1's priority: **description-vs-SQL contradictions** over exhaustive agent-ready scoring.

Scope narrowed to measures, FKs, and categoricals.

Grain + fan-out stay in the priority file.

## Input

You receive:
- `deep_pass_scope_rest`: deep-pass models excluding the top 5
- `inventory_json`: the canonical inventory
- `catalogs.description_contradicts_sql`: starter list of deterministic contradictions

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary.

```json
{
  "model_summaries": [
    {
      "model": "model_name",
      "columns_with_contradictions": 1,
      "columns_agent_ready": 6,
      "columns_not_ready_but_fixable": 2
    }
  ],

  "description_contradictions": [
    {
      "model": "model_name",
      "column": "column_name",
      "kind": "copy_paste|scope|agg_mismatch|stale_reference|self_contradiction|unit_missing_on_measure",
      "description_says": "quoted snippet",
      "sql_does": "quoted snippet",
      "agent_failure": "one sentence"
    }
  ],

  "description_findings": [
    {
      "model": "model_name",
      "column": "column_name",
      "column_type": "measure|categorical|fk|date",
      "current_description": "string or null",
      "agent_ready": false,
      "gap": "what specifically is missing"
    }
  ]
}
```

## Instructions

### Column scope cap

Only assess columns matching one of:
- **Measure-like names**: contains amount, count, sum, total, rate, revenue, cost, price, quantity, average, qty, fee
- **Categorical-like names**: contains status, type, category, tier, method, mode, state, level, kind, reason, priority
- **Foreign keys**: ends in `_id` AND appears as a column name in another model's YAML per the inventory

Skip every other column.

### Priority #1: description contradictions (same as A1)

For each in-scope column:
1. **Validate `catalogs.description_contradicts_sql`** entries for this model (confirm or mark `DISCARD` with reason).
2. **Find additional contradictions** the regex missed, using the same kinds: copy_paste, scope, agg_mismatch, stale_reference, self_contradiction, unit_missing_on_measure.

### Priority #2: residual description gaps

Only for columns NOT in `description_contradictions`. Flag an agent-critical ambiguity with a short `gap` (e.g., "FK target model unclear", "measure doesn't specify if refunds deducted", "categorical with no value list").

Do NOT enumerate every column with a verdict. If the description is clearly fine, skip it.

### Per-model summary required

Always include a row in `model_summaries` for every model in the scope, even if no contradictions or findings. Counts must be exact.

**Duplicate guard:** `(model, column)` tuple appears at most once in `description_contradictions` and at most once in `description_findings`. If both apply, put it only in `description_contradictions`.

### What this file does NOT do

- No grain analysis (priority file handles this)
- No fan-out risk (priority file handles this)
- No assessment of date/time columns or "other" columns
