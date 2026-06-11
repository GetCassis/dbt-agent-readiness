# Doc-vs-SQL phase

Check whether documentation claims match what the SQL actually does. This is the highest-value deep pass check: it catches cases where an agent would trust the docs and get wrong answers.

## Input

You receive:
- `deep_pass_scope`: list of model names to assess
- `inventory_json`: the canonical inventory

## Scope selection

Do NOT read every model in the deep pass scope. Prioritize in this order:
1. Models with 3+ inbound refs (hub models many others depend on)
2. Models in the reference/reporting layer
3. Models containing aggregation logic (SUM, COUNT, AVG)
4. Models with semantic measures

**Hard cap:** Audit at most 40 models, even if the deep pass scope is larger. For large scopes, the top 40 by priority gives better coverage than rushing through 79.

**Minimum:** At least 5 models (or all if fewer than 5 are in scope).

**Report coverage:** Track exactly how many models you audited vs how many were in scope. Include these counts in the output JSON (`models_audited` array length vs `models_in_scope` count).

**Large SQL files (>300 lines):** Do not read the entire file. Read the final 150 lines first (the final SELECT and its immediate CTEs). If you need upstream context, search for specific CTE names referenced in the final SELECT. This prevents context exhaustion on models with 1000+ line SQL.

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this JSON structure:

```json
{
  "models_in_scope": 0,
  "models_audited": ["model_a", "model_b"],
  "models_skipped": ["model_c"],

  "contradictions": [
    {
      "model": "model_name",
      "type": "filter_mismatch|aggregation_mismatch|column_reference_mismatch|coalesce_hidden|scope_mismatch|measure_vs_sql",
      "description_claim": "what the description says",
      "sql_reality": "what the SQL actually does",
      "impact": "what an agent would get wrong",
      "confidence": "high|medium",
      "file_path": "/path/to/file",
      "approximate_line": 0
    }
  ],

  "possible_issues": [
    {
      "model": "model_name",
      "observation": "what looks suspicious",
      "reasoning": "why it might be a problem",
      "confidence": "low"
    }
  ]
}
```

## Instructions

For each prioritized model:

1. **Read the full SQL file.**
2. **Read the full YAML descriptions** (model and column level, including doc() blocks).
3. **Check for contradictions:**

**Filter mismatches:** Description says "all X" but SQL has a WHERE clause that excludes some X. Or description says "excludes Y" but SQL includes Y.

**Aggregation mismatches:** Description says "count of Z" but SQL does SUM. Or description says "average" but SQL does COUNT.

**Column reference mismatches:** Description references a column, table, or join that doesn't appear in the SQL.

**Hidden COALESCEs:** SQL has COALESCE or fallback defaults that the description doesn't mention. Data could silently be NULL or a default value.

**Scope mismatches:** Description implies a broader or narrower scope than the SQL implements (e.g., "all customers" vs SQL that filters to active only).

**Measure-vs-SQL (if semantic layer exists):** Semantic measure `expr` is inconsistent with the model's actual SQL logic.

4. **Rate confidence:**
- **High:** clear contradiction between documented behavior and SQL logic
- **Medium:** likely contradiction but requires domain knowledge to confirm
- **Low:** suspicious but could be intentional (put in `possible_issues`)

**Calibration:** Only flag contradictions where you're confident the description and SQL disagree. Minor wording differences or vague descriptions are not contradictions. Be careful with CTEs: trace through the full query to understand what the final output includes.
