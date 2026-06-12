# Naming phase

Deterministic catalogs already enumerate the full naming landscape (`catalogs.concept_variants`, `catalogs.same_name_different_grain`, `catalogs.convention_drift`, `catalogs.enum_value_gaps.casing_mismatches`, `catalogs.unit_variants`, `catalogs.unprefixed_booleans`). Your job is NOT to re-catalog them. Your job is to identify **violations of the project's own implicit convention** — the cases where an agent following the dominant pattern would miss rows.

## Input

You receive:
- `deep_pass_scope`: list of models to assess
- `inventory_json`: the canonical inventory (column names, layers, descriptions)
- The catalogs referenced above are already populated — consume them, don't re-derive.

## Output

Your entire response must be a single raw JSON object. No markdown code fences.

```json
{
  "convention_violations": [
    {
      "convention": "boolean_prefix|temporal_suffix|enum_casing|currency_suffix|language_mix",
      "dominant_pattern": "e.g. 'is_' prefix on 70/75 booleans",
      "violators": [
        {"model": "model_a", "column": "user_is_active", "why": "is_ is infix not prefix — WHERE is_active misses this row"}
      ],
      "agent_failure": "one sentence on what breaks"
    }
  ],

  "same_name_different_meaning": [
    {
      "column": "amount",
      "occurrences": [
        {"model": "model_a", "description": "per-payment amount", "grain_context": "one row per payment"},
        {"model": "model_b", "description": "per-order total", "grain_context": "one row per order"}
      ],
      "risk": "what an agent would get wrong"
    }
  ],

  "language_mixing": {
    "severity": "significant|minor|none",
    "primary_language": "english",
    "secondary_language": "french",
    "non_english_column_count": 45,
    "total_column_count": 180,
    "examples": [
      {"type": "column_name", "model": "model_a", "value": "technicien", "english_equivalent": "technician"},
      {"type": "enum_value", "model": "model_b", "column": "housing_status", "documented_value": "occupé", "actual_value": "EQUIPPED"}
    ]
  }
}
```

Do NOT produce the old `abbreviation_inconsistency` / `naming_conventions` blocks. The deterministic catalogs cover those; surfacing them here is duplicate noise.

## Instructions

### Convention violations (primary output)

For each convention area, find the dominant pattern first. Only flag violators when:

1. A dominant pattern exists (one variant covers ≥80% of the population, OR explicit project convention in README/CLAUDE.md), AND
2. At least 3 columns violate it, OR at least one high-traffic column does (inbound_refs ≥ 3 on the model), AND
3. The violation would cause an agent to miss data with the "obvious" filter.

Examples that DO qualify:
- `user_is_active`, `offerer_is_active`, `venue_is_active` (infix `is_`) when 70/75 booleans are prefix `is_active`. Agent filter `WHERE is_active` misses every entity-namespaced flag.
- `customer_id` (dominant) vs `cust_id` on one or two models. Agent joins on `customer_id` miss the `cust_id` models.
- `status` lowercase in some models, `STATUS` uppercase in others, enum values `'EQUIPPED'` vs `'equipped'`. Cross-filter on one casing misses the other.

Examples that do NOT qualify (deterministic catalog already handles):
- "This project has 52 `fact_` and 19 `dim_` and 1 unprefixed model" → belongs in `catalogs.convention_drift.mart_prefix_mix`, not here.
- "Project has 3 columns ending `_at`, 7 ending `_date`, 1 ending `_timestamp`" → belongs in `catalogs.convention_drift.temporal_suffix_mix`, not here.

### Same-name-different-meaning

Unchanged. Find columns with identical names across models where the meaning, grain, or scope differs materially. Use descriptions and grain context.

### Language mixing

Unchanged. Classify significance:
- **Significant** (>20% of columns or enum values in a non-English language): HIGH-impact. List top 10 examples of the kind of literal an English-writing agent would miss.
- **Minor** (<20%): informational.
- **None**: skip.

### What NOT to output

- Do NOT produce a "date suffixes are inconsistent" line — the catalog already does.
- Do NOT list every boolean prefix count — the catalog does.
- Do NOT enumerate every concept variant — the `catalogs.concept_variants` already does, with SQL alias evidence.
- Do NOT catalog every enum casing mismatch — `catalogs.enum_value_gaps.casing_mismatches` already does, and synthesis emits it directly.

Focus on **violations that bite the agent**, not drift tallies.
