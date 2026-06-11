# Inventory phase: deep analysis (priority models only)

Full-depth inventory for priority models (those with 3+ inbound refs). This is the high-value analysis: grain detection, doc() resolution, full SQL column extraction, phantom column detection.

**You only process the priority models you are given.** Do not scan the full project.

## Input

You receive:
- `project_path`: absolute path to the dbt project root
- `model_paths`: directories containing models (from dbt_project.yml)
- `priority_models`: list of model names to process (these have 3+ inbound refs)
- `global_configs`: severity settings, vars, etc.

## Output

Your entire response must be a single raw JSON object. Start with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences.

Return EXACTLY this JSON structure:

```json
{
  "layer_scope": "priority-deep",
  "models": [
    {
      "name": "model_name",
      "sql_path": "/absolute/path/to/model.sql",
      "yaml_path": "/absolute/path/to/schema.yml or null",
      "layer": "staging|intermediate|core|reference|other",
      "has_description": true,
      "description_quality": "good|placeholder|restates_name|empty|none",
      "description_text": "first 200 chars of description or null",
      "grain_declared": false,
      "grain_statement": "string or null",
      "column_count_yaml": 0,
      "column_count_sql": 0,
      "columns_with_descriptions": 0,
      "has_pk_test": true,
      "pk_column": "column_name or null",
      "inbound_refs": -1,
      "outbound_refs": ["model_a", "model_b"],
      "has_semantic_model": false,
      "materialization": "view|table|incremental|ephemeral|unknown"
    }
  ],

  "columns": [
    {
      "model": "model_name",
      "column": "column_name",
      "has_description": true,
      "description_text": "first 200 chars or null",
      "tests": ["unique", "not_null", "relationships:other_model.col", "accepted_values:a,b,c"]
    }
  ],

  "sources": [
    {
      "source_name": "string",
      "table_name": "string",
      "has_description": true,
      "has_freshness": false,
      "yaml_path": "/absolute/path"
    }
  ],

  "semantic_layer": {
    "semantic_models": [
      {
        "name": "string",
        "model_ref": "model_name",
        "has_description": true,
        "entities": [
          {"name": "string", "type": "primary|foreign|unique|natural", "expr": "string or null"}
        ],
        "measures": [
          {"name": "string", "agg": "sum|count|avg|min|max|count_distinct|etc", "expr": "string or null", "has_description": true, "description_text": "first 200 chars or null"}
        ],
        "dimensions": [
          {"name": "string", "type": "categorical|time|etc", "expr": "string or null"}
        ]
      }
    ],
    "metrics": [
      {"name": "string", "type": "simple|derived|ratio|cumulative", "measure_refs": ["measure_name"], "has_description": true, "has_filter": false}
    ],
    "saved_queries": [
      {"name": "string", "metric_refs": ["metric_name"]}
    ]
  },

  "issues": {
    "phantom_columns": [{"model": "string", "column": "string", "yaml_path": "string", "reason": "in YAML but not in SQL output"}],
    "duplicate_yaml_columns": [{"model": "string", "column": "string", "descriptions_differ": true}],
    "copy_paste_descriptions": [{"model": "string", "items": ["col_a", "col_b"], "shared_description": "string", "why_wrong": "string"}],
    "source_via_ref": [{"model": "string", "target": "string", "reason": "uses ref() to reach raw source instead of source()"}]
  },

  "seeds": [
    {"name": "string", "path": "string", "appears_to_define": "string"}
  ],

  "exposures": [
    {"name": "string", "depends_on": ["model_a", "model_b"]}
  ]
}
```

Note: `inbound_refs` is set to -1 (unknown). The orchestrator computes this after merging with the scan inventory.

## Instructions

Work through these steps sequentially. Read every file for every priority model. Report exact counts.

### Step 1: Read all YAML files for priority models

First, use Glob to find all `**/*.yml` and `**/*.yaml` under model paths (exclude `dbt_packages/`, `target/`). Also search for YAML files at the project root that may define semantic models, metrics, or exposures.

**Glob fallback:** If Glob returns 0 results for a pattern under a model directory, retry with Bash: `find {dir} -name '*.yml' -not -path '*/dbt_packages/*' -not -path '*/target/*'`. Use the Bash output.

Read each YAML file. For each model that matches a name in `priority_models`, extract:
- `models:` entries → name, description, columns (name, description, tests)
- `semantic_models:` entries → name, model ref, entities, measures, dimensions
- `metrics:` entries → name, type, measure refs, description, filters
- `saved_queries:` entries → name, metric refs
- `sources:` entries → name, tables, freshness config (if any source definitions live alongside priority models)
- `exposures:` entries → name, depends_on

**Handle `{{ doc() }}` references:** When a description uses `{{ doc("block_name") }}`, find the referenced doc block. Search for files named `docs.md`, `docs/*.md`, or files containing `{% docs block_name %}`. Read the doc block content. Use the doc block content as the actual description for quality assessment. Do NOT flag doc() references as missing descriptions.

**Description quality classification:**
- `good`: provides meaningful context (>10 chars, not just the column name restated)
- `placeholder`: contains "doc pour", "TODO", "TBD", or similar placeholder text
- `restates_name`: description is essentially the column name with spaces (e.g., `order_id` → "Order ID")
- `empty`: description key exists but value is empty or whitespace
- `none`: no description key at all

**Grain detection:** Check model descriptions for grain statements: "one row per", "one record per", "one entry per", "grain:", "each record represents", "unique on". If found, set `grain_declared: true` and record the statement.

### Step 2: Read all SQL files for priority models

For each priority model's SQL file:
- Extract `ref()` calls → `outbound_refs`
- Extract `source()` calls → note which models use sources
- **Extract columns from the final SELECT statement and set `column_count_sql` to the count.** This is critical for phantom column detection.
  - If the final SELECT is `SELECT * FROM cte`, trace back through CTEs to find actual columns
  - If the SQL uses macros that generate columns, note this and fall back to YAML column list
  - For very large SQL files (>500 lines), focus on the final CTE or SELECT that produces the model output
  - `column_count_sql` must be >0 for every model that has a readable SQL file. If you cannot determine the count, set it to -1 (not 0) so downstream phases know parsing failed vs was skipped.

**Self-check:** After processing all SQL files, count how many priority models have `column_count_sql = 0`. If more than 20% have 0, something went wrong. Re-read the top 5 models (by name from the priority list) and retry SQL column extraction for those.

**Check for `ref()` vs `source()` misuse:** If a model uses `ref()` to reach what appears to be a raw/source table (table name matches a source definition), flag it.

### Step 3: Cross-reference (within priority models)

For each priority model:
- **Phantom column detection:** Compare YAML columns vs SQL columns, but ONLY when `column_count_sql > 0`. When `column_count_sql = -1` (macro-heavy, parsing failed), skip phantom detection for that model and note: "Phantom column detection skipped: SQL column extraction failed (macro-heavy model)." Never report phantom columns for a model where you couldn't parse the SQL.
- Check for duplicate column names within the same YAML model entry → flag duplicates
- Do NOT compute inbound_refs (set to -1). The orchestrator handles cross-inventory ref counting.
- Do NOT check for broken refs. A ref() target might be in the scan inventory.

**Copy-paste detection:** For each model, check if multiple columns share identical descriptions when they shouldn't (different `expr` or different column names implying different concepts). Also check across measures in semantic models.

### Step 4: Read seeds and exposures

Use Glob to find `seeds/**/*.csv` and any YAML files defining exposures. Catalog seeds and exposures.

### Step 5: Assemble and return

Build the JSON. Double-check:
- Every model in `columns` exists in `models`
- Every model in `semantic_layer` semantic models exists in `models`
- No approximate counts
- `column_count_sql` is not 0 for any model (must be >0 or -1)

Return the JSON.
