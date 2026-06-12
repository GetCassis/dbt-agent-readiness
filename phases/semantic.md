# Semantic layer phase

Deep-dive into the dbt semantic layer (MetricFlow). Only run if the inventory shows semantic models exist.

## Input

You receive:
- `deep_pass_scope`: list of model names to assess
- `inventory_json`: the canonical inventory (use `semantic_layer` section)

Read the actual YAML files for detailed assessment. The inventory has summaries; you need the full definitions.

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this JSON structure:

```json
{
  "measure_findings": [
    {
      "semantic_model": "string",
      "measure": "measure_name",
      "agg": "sum|count|etc",
      "expr": "string or null",
      "has_description": true,
      "description_text": "string or null",
      "issues": ["no description", "description doesn't mention filter in expr", "agg mismatch: desc says average but agg is sum"]
    }
  ],

  "entity_findings": [
    {
      "semantic_model": "string",
      "entity": "entity_name",
      "type": "foreign",
      "target_model": "string",
      "target_exists_in_project": true,
      "model_refs_target": true,
      "issues": ["target model not found in project", "model SQL does not ref() the target"]
    }
  ],

  "dimension_findings": [
    {
      "semantic_model": "string",
      "dimension": "dimension_name",
      "expr": "string or null",
      "column_exists_in_model": true,
      "issues": ["phantom dimension: column not found in model SQL"]
    }
  ],

  "metric_findings": [
    {
      "metric": "metric_name",
      "type": "simple|derived|ratio|cumulative",
      "issues": ["measure ref 'xyz' not found in any semantic model", "filter references non-existent dimension"]
    }
  ],

  "saved_query_coverage": {
    "covered_metrics": ["metric_a", "metric_b"],
    "uncovered_metrics": ["metric_c", "metric_d"]
  },

  "risk_adjustments": {
    "cant_join_adjustment": "reduce|no_change|increase",
    "cant_join_reason": "entity FKs declare N/M join paths",
    "wrong_numbers_adjustment": "reduce|no_change|increase",
    "wrong_numbers_reason": "N measures have good descriptions, M are undescribed",
    "has_to_guess_adjustment": "reduce|no_change|increase",
    "has_to_guess_reason": "semantic layer covers core concepts with N measures and M dimensions"
  }
}
```

## Instructions

### Measure description quality

For each measure in every semantic model, read the full YAML. Check:

1. **Has description?** An undescribed measure is worse than no semantic layer: it gives agents false confidence.
2. **Does description specify inclusion/exclusion scope?** Same rigor as column agent-readiness. Does it say what's in and out?
3. **Does description match the `agg` type?** If description says "average" but `agg` is `sum`, flag.
4. **If `expr` has a filter or CASE WHEN, does the description mention it?** A measure with `expr: "CASE WHEN is_food_item THEN product_price END"` described as just "Revenue" is misleading.
5. **Copy-paste detection:** If two measures have identical descriptions but different `expr` fields, flag.

### Entity-to-ref consistency

For each `type: foreign` entity:
- Does the target model exist in the project?
- Does the owning model's SQL actually `ref()` the target?
- Count valid entity FKs. These reduce "can't join" risk.

### Dimension-to-column validation

For each dimension:
- Does the dimension's `expr` or `name` resolve to an actual column in the model's SQL output?
- Flag phantom dimensions.
- Check for numeric values typed as `type: categorical` (prevents aggregation).

### Metric-to-measure validation

For each metric:
- Does the `measure` reference resolve to an existing measure?
- For derived metrics: do arithmetic references resolve?
- For metrics with filters: do dimension references exist?
- Flag broken references.

### Saved query coverage

List which metrics have saved queries vs not. Informational only.

### Risk adjustment

Calculate adjustments for the synthesis:
- Count valid entity FKs vs total implicit relationships → "can't join" adjustment
- Count described vs undescribed measures → "wrong numbers" adjustment
- Overall semantic layer completeness → "has to guess" adjustment
