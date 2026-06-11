# Business terms phase

Detect recurring business terms that lack canonical definitions. When multiple models use the same term with different meanings, an agent's answer depends on which model it picks.

## Input

You receive:
- `deep_pass_scope`: list of model names to assess
- `inventory_json`: the canonical inventory (use `columns`, `semantic_layer.measures`, `semantic_layer.metrics`)
- `glossary_path` (optional): absolute path to a business glossary file
  (`.md` / `.csv`). If present, read it yourself with the Read tool. Do not
  expect the content inline in your prompt. If the file doesn't exist or is
  unreadable, proceed without it and note that in the output.

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this JSON structure:

```json
{
  "recurring_terms": [
    {
      "term": "revenue",
      "occurrences": [
        {"model": "orders", "context": "column: order_total, described as 'total including tax'"},
        {"model": "order_items", "context": "measure: revenue, described as 'sum of product_price'"},
        {"model": "customers", "context": "column: lifetime_spend, described as 'sum of order_total'"}
      ],
      "has_canonical_definition": false,
      "inconsistencies": "revenue in order_items excludes tax, but lifetime_spend in customers includes tax via order_total",
      "risk": "agent asked 'what is our revenue?' gets different numbers depending on which model it queries"
    }
  ],

  "enum_gaps": [
    {
      "column": "product_type",
      "models": ["products", "stg_products"],
      "known_values": "jaffle, beverage (inferred from SQL boolean logic in stg_products.sql)",
      "value_source": "SQL inference|seed file|doc block|description|none",
      "has_accepted_values_test": false,
      "risk": "agent writes WHERE product_type = 'food' and gets zero rows"
    }
  ],

  "seed_gaps": [
    {
      "seed": "seed_name",
      "defines_values_for": "what business concept",
      "connected_to_tests": false,
      "related_columns": ["model.column"]
    }
  ]
}
```

## Instructions

### Recurring terms

Scan column names, descriptions, measure names, and metric names across the project. Identify terms that appear in 3+ models: revenue, cost, active, customer, churn, MRR, order, amount, spend, profit, etc.

For each recurring term:
1. Check if a canonical definition exists anywhere: model description, metric definition, doc() block, glossary file
2. Check if different models define it differently (with vs without tax, gross vs net, etc.)
3. Rate the risk: could an agent get different numbers for the same question depending on which model it picks?

### Enum gaps

From the inventory's `categorical_columns_without_accepted_values` list, and from your own scan of column names suggesting categorical values:

For each categorical column:
1. Can valid values be found anywhere? (SQL logic, seed files, doc blocks, descriptions)
2. If found: where? Are they documented or just buried in SQL?
3. If not found: flag the risk (agent has to guess valid values for WHERE clauses)

### Seed gaps

From the inventory's `seeds` list:
- Do any seeds define reference data (country codes, status enums, tier mappings)?
- Are those values connected to `accepted_values` tests on related columns?
- If seeds exist but aren't connected to tests: the reference data exists but isn't enforced
