# Inventory phase: lightweight scan (all models)

YAML-only scan of every model in the project. This produces the base inventory that the orchestrator merges with the deep inventory. Speed is the priority: read YAML files and extract refs from SQL, but do NOT parse SQL for column counts, grain, or doc() blocks.

## Input

You receive:
- `project_path`: absolute path to the dbt project root
- `model_paths`: directories containing models (from dbt_project.yml)
- `layer_classification`: which layer each model directory maps to
- `global_configs`: severity settings, vars, etc.

## Output

Your entire response must be a single raw JSON object. Start with `{` and end with `}`. No text before the opening brace. No text after the closing brace. No markdown code fences.

Return EXACTLY this JSON structure:

```json
{
  "layer_scope": "all-scan",
  "models": [
    {
      "name": "model_name",
      "sql_path": "/absolute/path/to/model.sql",
      "yaml_path": "/absolute/path/to/schema.yml or null",
      "layer": "staging|intermediate|core|reference|other",
      "has_description": true,
      "description_quality": "good|placeholder|restates_name|empty|none",
      "description_text": "first 200 chars of description or null",
      "grain_declared": null,
      "grain_statement": null,
      "column_count_yaml": 0,
      "column_count_sql": null,
      "columns_with_descriptions": 0,
      "has_pk_test": false,
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
      "tests": ["unique", "not_null"]
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

  "issues": {
    "phantom_models": [{"name": "string", "yaml_path": "string", "reason": "YAML entry but no SQL file"}],
    "duplicate_yaml_columns": [{"model": "string", "column": "string", "descriptions_differ": true}]
  }
}
```

**Key fields set to null (not attempted):**
- `grain_declared`: null (deep inventory handles grain)
- `grain_statement`: null
- `column_count_sql`: null (deep inventory handles SQL parsing)

**`inbound_refs`:** Set to -1 (unknown). The orchestrator computes this after merging.

## Instructions

Work through these steps. Prioritize speed.

### Step 1: Find all files

Use Glob to find all files under model paths (exclude `dbt_packages/`, `target/`):
- `**/*.yml` and `**/*.yaml` for schema files
- `**/*.sql` for model files

**Glob fallback:** If Glob returns 0 results for a pattern under a model directory, retry with Bash: `find {dir} -name '*.sql' -not -path '*/dbt_packages/*' -not -path '*/target/*'`. Use the Bash output to build the file list.

### Step 2: Read all YAML files

For each YAML file, read it and extract:
- `models:` entries: name, description, columns (name, description, tests), materialization config
- `sources:` entries: name, tables, freshness config
- `semantic_models:` entries: just note which model each references (set `has_semantic_model: true`)
- `exposures:` entries: just note `depends_on` model names

**Description quality (simplified for non-stg_ models):**
- `good`: provides meaningful context (>10 chars, not just the column name restated)
- `placeholder`: contains "TODO", "TBD", "doc pour", or similar
- `restates_name`: description is essentially the column name with spaces
- `empty`: description key exists but value is empty or whitespace
- `none`: no description key at all

**For `stg_` prefixed models:** Classify descriptions as good/placeholder/none only (skip restates_name/empty distinction). Do NOT build individual `columns[]` entries. Just count `column_count_yaml` and `columns_with_descriptions`.

**Do NOT resolve `{{ doc() }}` references.** If a description is only a doc() reference, classify as `good` (the deep inventory will resolve it).

**Do NOT assess grain.** Set `grain_declared: null` and `grain_statement: null` for all models.

### Step 3: Extract refs from SQL files (lightweight)

For each SQL file:
- Extract `ref()` calls → `outbound_refs`
- Extract `source()` calls → also note in `outbound_refs` as "source:source_name.table_name"
- **Do NOT parse SQL for column counts.** Set `column_count_sql` to null.

**Read only what's needed:** You can use Grep to find `ref()` and `source()` patterns without reading full SQL files. This is faster for large projects.

### Step 4: Cross-reference (lightweight)

- Check if every YAML model entry has a corresponding SQL file → flag phantom models
- Check for duplicate column names within YAML entries → flag duplicates
- Do NOT compute inbound_refs (set to -1). Do NOT check for broken refs.
- Do NOT check for phantom columns (no SQL column counts available).

### Step 5: Assemble and return

Build the JSON. Double-check:
- Every model in `columns` exists in `models`
- `sources` includes all source definitions found
- `stg_` models do NOT have individual column entries in `columns[]`

Return the JSON.
