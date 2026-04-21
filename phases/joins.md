# Joins phase

Analyze join paths, detect missing relationships, unused joins, and entry point ambiguity.

## Input

You receive:
- `deep_pass_scope`: list of model names to assess
- `inventory_json`: the canonical inventory (use `models`, `relationships`, `columns`)

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this JSON structure:

```json
{
  "entry_points": [
    {
      "model": "model_name",
      "classification": "entry_point|building_block|ambiguous",
      "signals": ["in marts/ directory", "zero inbound refs", "has exposure"]
    }
  ],

  "model_overlap": [
    {
      "models": ["orders", "orders_kpis"],
      "overlapping_question": "what is our total revenue?",
      "disambiguated": false,
      "explanation": "both contain revenue columns at different grains, descriptions don't clarify which to use"
    }
  ],

  "unused_joins": [
    {
      "model": "model_name",
      "joined_model": "joined_model_name",
      "sql_path": "/path/to/model.sql",
      "explanation": "table is joined but no columns from it appear in SELECT, WHERE, or GROUP BY"
    }
  ],

  "missing_pk_tests": [
    {
      "model": "model_name",
      "inbound_refs": 5,
      "likely_pk": "column_name",
      "has_unique": false,
      "has_not_null": false
    }
  ],

  "undeclared_relationships": [
    {
      "from_model": "string",
      "from_column": "string",
      "to_model": "string",
      "to_column": "string",
      "evidence": "ref() dependency exists but no relationship test or entity FK"
    }
  ]
}
```

## Instructions

### Entry point classification

For each model in scope, classify as:

**Entry point** (agent should query directly):
- In `marts/`, `reference/`, `reporting/`, `presentation/`, `core/` directory
- Name starts with `dim_` or `fact_` (canonical query targets in most dbt projects)
- Zero inbound refs (leaf node in DAG)
- Has an exposure referencing it
- Description says "use this for...", "reporting model for..."

**Building block** (agent should not query directly):
- In `staging/`, `intermediate/`, `prep/`, `utils/`
- Name starts with `stg_`, `int_`, `prep_`, `base_`

**Ambiguous** (no clear signal):
- Doesn't match either pattern and has no recognized layer directory or naming prefix
- Models with `dim_`/`fact_` prefixes or in recognized layer directories should classify as entry point or building block, not ambiguous

If >30% of models in scope are genuinely ambiguous (after applying prefix heuristics), flag: "An agent has no way to distinguish queryable models from internal building blocks."

### Model overlap

Find groups of models that could answer the same business question. Check if their descriptions disambiguate them. Only flag overlaps where descriptions don't make the distinction clear.

### Unused joins

For each model in scope, read the SQL. Identify all JOIN clauses. For each joined table:
- Check if any column from that table appears in SELECT, WHERE, GROUP BY, or HAVING
- If not, flag as unused: adds cost, may cause silent row multiplication

### Missing PK tests on referenced models

For each model with inbound_refs > 0 (from inventory), check if it has a column with both `unique` and `not_null` tests. If not, flag it: silent fan-out risk for every model that joins to it.

### Undeclared relationships

From the inventory's `relationships.implicit` list, highlight the highest-risk ones: FK columns between core/reference models with no declared relationship.

**Per-ref() mapping:** For each model in scope, read its SQL and list every `ref()` call. For each ref() target, check whether a `relationships` test exists for that specific join. Include each unmapped ref()-to-relationship pair in the `undeclared_relationships` array. Do not just report "zero relationship tests" globally; the synthesis step needs per-model, per-ref() data.

**FK target resolution:** When identifying implicit FK targets for an `_id` column, prefer the model referenced via `ref()` in the SQL over name-based guessing. Example: if `int_order_payments.sql` contains `ref('stg_payments')`, then `int_order_payments.order_id` likely joins to `stg_payments`, not to `stg_orders`, even though `stg_orders` also has an `order_id` column.

### Lineage depth

Compute from inventory `outbound_refs`: for each model in scope, count the longest chain of refs back to a source or model with zero outbound refs. This is a pure computation over the inventory data (no file reads needed).

Flag models that are >6 refs deep from any source. An agent tracing data lineage through 7+ files loses context rapidly.

Add to the output JSON:

```json
"lineage_depth": [
  {
    "model": "model_name",
    "max_depth": 8,
    "deepest_path": ["source_a", "stg_x", "int_y", "int_z", "dim_w", "fact_v", "ref_u", "model_name"]
  }
]
```

Only include models with depth > 6. If none exceed 6, return an empty array.
