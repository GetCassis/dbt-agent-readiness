# Inventory phase

Build the canonical project inventory. This is the single source of truth that all subsequent phases consume.

## Input

You receive:
- `project_path`: absolute path to the dbt project root
- `model_paths`: directories containing models (from dbt_project.yml)
- `layer_classification`: which layer each model directory maps to
- `global_configs`: severity settings, vars, etc.

## Output

Your entire response must be a single raw JSON object. Start with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences.

```json
{
  "project_name": "string",
  "total_models": 0,
  "total_schema_files": 0,
  "total_sources": 0,
  "global_severity_warn": false,
  "has_semantic_layer": false,

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
      "inbound_refs": 0,
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

  "relationships": {
    "declared": [
      {"from_model": "string", "from_column": "string", "to_model": "string", "to_column": "string", "source": "test|entity_fk"}
    ],
    "implicit": [
      {"from_model": "string", "from_column": "string", "to_model": "string", "to_column": "string", "reason": "string"}
    ]
  },

  "issues": {
    "broken_refs": [{"model": "string", "refs": "nonexistent_model", "sql_path": "string"}],
    "phantom_models": [{"name": "string", "yaml_path": "string", "reason": "YAML entry but no SQL file"}],
    "phantom_columns": [{"model": "string", "column": "string", "yaml_path": "string", "reason": "in YAML but not in SQL output"}],
    "duplicate_yaml_columns": [{"model": "string", "column": "string", "descriptions_differ": true}],
    "copy_paste_descriptions": [{"model": "string", "items": ["col_a", "col_b"], "shared_description": "string", "why_wrong": "string"}],
    "source_via_ref": [{"model": "string", "target": "string", "reason": "uses ref() to reach raw source instead of source()"}]
  },

  "test_summary": {
    "unique_tests": 0,
    "not_null_tests": 0,
    "relationship_tests": 0,
    "accepted_values_tests": 0,
    "other_tests": 0,
    "models_with_zero_tests": 0,
    "models_with_zero_tests_list": ["model_a", "model_b"],
    "categorical_columns_without_accepted_values": ["model.column", "model.column"]
  },

  "seeds": [
    {"name": "string", "path": "string", "appears_to_define": "string"}
  ],

  "exposures": [
    {"name": "string", "depends_on": ["model_a", "model_b"]}
  ]
}
```

## Instructions

Work through these steps sequentially. Read every file. Do not estimate or approximate. Report exact counts.

### Step 1: Read all YAML files

Use Glob to find all `**/*.yml` and `**/*.yaml` under model paths (exclude `dbt_packages/`, `target/`).

**Glob fallback:** If Glob returns 0 results for a pattern under a model directory, retry with Bash: `find {dir} -name '*.yml' -not -path '*/dbt_packages/*' -not -path '*/target/*'`. Use the Bash output to build the file list.

For each YAML file, read it and extract:
- `models:` entries → name, description, columns (name, description, tests), meta tags (if present)
- `semantic_models:` entries → name, model ref, entities, measures, dimensions
- `metrics:` entries → name, type, measure refs, description, filters
- `saved_queries:` entries → name, metric refs
- `sources:` entries → name, tables, freshness config
- `exposures:` entries → name, depends_on

**Meta tags (opportunistic):** If models or columns have `meta:` tags, note them in the inventory. These carry agent-relevant signals (PII flags, ownership, data classification). Don't add a dedicated check; just preserve them in the JSON so downstream phases can reference them.

**Handle `{{ doc() }}` references:** When a description uses `{{ doc("block_name") }}`, find the referenced doc block. Search for files named `docs.md`, `docs/*.md`, or files containing `{% docs block_name %}`. Read the doc block content. Use the doc block content as the actual description for quality assessment. Do NOT flag doc() references as missing descriptions.

**Description quality classification:**
- `good`: provides meaningful context (>10 chars, not just the column name restated)
- `placeholder`: contains "doc pour", "TODO", "TBD", or similar placeholder text
- `restates_name`: description is essentially the column name with spaces (e.g., `order_id` → "Order ID")
- `empty`: description key exists but value is empty or whitespace
- `none`: no description key at all

**Grain detection:** Check model descriptions for grain statements: "one row per", "one record per", "one entry per", "grain:", "each record represents", "unique on". If found, set `grain_declared: true` and record the statement.

### Step 2: Read all SQL files

Use Glob to find all `**/*.sql` under model paths (exclude `dbt_packages/`, `target/`).

**Glob fallback:** If Glob returns 0 results, retry with Bash: `find {dir} -name '*.sql' -not -path '*/dbt_packages/*' -not -path '*/target/*'`.

For each SQL file:
- Extract `ref()` calls → these are `outbound_refs`
- Extract `source()` calls → note which models use sources
- **Extract columns from the final SELECT statement and set `column_count_sql` to the count.** This is critical for phantom column detection downstream.
  - If the final SELECT is `SELECT * FROM cte`, trace back through CTEs to find actual columns
  - If the SQL uses macros that generate columns, note this and fall back to YAML column list
  - For very large SQL files (>500 lines), focus on the final CTE or SELECT that produces the model output
  - `column_count_sql` must be >0 for every model that has a readable SQL file. If you cannot determine the count, set it to -1 (not 0) so downstream phases know parsing failed vs was skipped.

**Self-check:** After processing all SQL files, count how many models have `column_count_sql = 0`. If more than 20% have 0, something went wrong. Re-read the 5 models with the highest `column_count_yaml` and retry SQL column extraction for those.

**Check for `ref()` vs `source()` misuse:** If a model uses `ref()` to reach what appears to be a raw/source table (table name matches a source definition), flag it.

### Step 3: Cross-reference

For each model:
- Compute `inbound_refs` by counting how many other models include it in their `outbound_refs`
- Check if every `ref()` target has a corresponding SQL file → flag broken refs. **Exception:** if the ref target matches a seed name (from `seeds/` directory) or a snapshot name (from `snapshots/` directory), note it as "possible issue (may resolve at compile time)" rather than a broken ref.
- Check if every YAML model entry has a corresponding SQL file → flag phantom models
- **Phantom column detection:** Compare YAML columns vs SQL columns, but ONLY when `column_count_sql > 0`. When `column_count_sql = -1` (macro-heavy, parsing failed), skip phantom detection for that model. Never report phantom columns for a model where you couldn't parse the SQL.
- Check for duplicate column names within the same YAML model entry → flag duplicates

**Copy-paste detection:** For each model, check if multiple columns share identical descriptions when they shouldn't (different `expr` or different column names that imply different concepts). Also check across measures in semantic models.

### Step 4: Build test summary

Count all tests by type. Identify:
- Models with zero tests
- PK columns (with `unique` + `not_null`) per model
- Categorical columns (named `status`, `type`, `category`, `tier`, `method`, `mode`, `state`, `level`, `kind`, `reason`, `priority`) without `accepted_values` tests
- FK columns (`_id` suffix in multiple models) without `relationships` tests

### Step 5: Build relationship inventory

**Declared relationships:** From `relationships` tests and from semantic model `type: foreign` entities.

**Implicit relationships:** FK columns (`_id` suffix) that appear in multiple models but have no declared relationship (no test, no entity FK).

### Step 6: Assemble and return

Build the complete JSON object. Double-check:
- `total_models` matches the length of `models` array
- Every model referenced in `columns` exists in `models`
- Every model in `relationships` exists in `models`
- No approximate counts — every number is exact

Return the JSON.
