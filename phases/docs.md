# Docs-scan phase (Layer 2, light LLM)

Adjudicate the flagged rows that `scripts/docs_scan.py` produced. This phase runs
only when docs mode is on. It is deliberately cheap: you reason over short
snippets the deterministic scanner already extracted. Cost scales with the
number of flagged rows, not with documentation volume.

## Hard boundary (do not cross)

- **Never read whole documents.** You only ever see the snippets passed to you.
- **Never follow or fetch links** (Google Docs, Confluence, Notion, Slack, etc.).
- **Never re-scan the repo.** The identifier set, coverage, and pointers are
  already decided deterministically upstream and are not yours to recompute.

If a row's snippets are too thin to judge, return `can_t_tell`. That is a valid,
expected answer. Guessing is worse than abstaining.

## Input

You receive the `llm_queue` object from the docs-scan JSON (already hard-capped):

- `multi_home`: identifiers with more than one home, where a *home* is a doc
  that DEFINES the term (a heading subject, a column-dictionary row, a "`x`
  is/means …" definition, or a glossary entry), not one that merely mentions it
  in prose, SQL, or a checklist. Each carries `identifier`,
  `kind`, `is_dbt_identifier`, `authoritative_dbt_definition` (`exists`,
  `source`, `quality`), `doc_count`, and `sources` (each `origin` of
  `dbt_description` or `doc`, with a `ref` and a short `snippet`).
- `doc_column_claims`: a doc's claimed column list under a model heading, with
  `model`, `claimed_columns`, `model_yaml_columns`, and a `snippet`.
- `doc_classification`: `path`, `title`, deterministic `doc_type` guess.
- `dropped_beyond_cap`: counts of rows omitted by the cap. Pass these through so
  synthesis can report what was not adjudicated.

## Tasks (bounded, one line of reasoning each)

### 1. Multi-home verdict — do the homes agree?

For each `multi_home` row, compare the snippets and decide `agree`,
`differ`, or `can_t_tell`. "Differ" means the definitions are substantively
inconsistent (different scope, filter, grain, or measure), not merely worded
differently. Two snippets that say the same thing in different words `agree`.

You do NOT decide severity. Synthesis applies the conditional reliability rule
using the deterministic facts already on the row (`is_dbt_identifier`,
`authoritative_dbt_definition`, and `severity_if_differ`):

> Severity depends on the agent grounding model. For a **repo-grounded** agent
> (the realistic default: it reads the dbt project and the docs together and has
> no rule for which side wins), a confirmed `differ` on a dbt identifier is a
> **Blocker** whether or not dbt pins the term. For a **metadata-grounded** agent
> (it reads the dbt layer only), the same `differ` is a **Blocker** only when
> nothing pins the term (`authoritative_dbt_definition.exists` is false); when
> dbt pins it, that agent answers from the dbt layer, so it is **Hygiene**. A
> term that is not a dbt identifier is **context** for both.

Your job is only the `verdict`. Report it faithfully.

### 2. Doc-column-claim verdict — does the doc match the model's columns?

For each `doc_column_claims` row, compare `claimed_columns` against
`model_yaml_columns`: `matches` (every claimed column is a real model column),
`doc_lists_columns_model_lacks` (the doc claims columns the model does not have),
or `partial`. Name the specific offending columns. The deterministic
`column_drift` catalog already flags the high-confidence cases; your verdict
confirms or softens them and catches the ones where the model's column set was
only partially known.

### 3. Doc classification refinement

For each `doc_classification` row, confirm or correct the `doc_type` from the
title and snippet alone: one of `glossary`, `runbook`, `architecture`,
`onboarding`, `process`, `changelog`, `readme`, `other`.

## Output

Your entire response must be a single raw JSON object. No markdown code fences,
no commentary before or after.

```json
{
  "multi_home_verdicts": [
    {
      "identifier": "fct_revenue",
      "kind": "model",
      "verdict": "differ|agree|can_t_tell",
      "how_they_differ": "one line; empty if agree",
      "is_dbt_identifier": true,
      "authoritative_definition_exists": false,
      "severity_if_differ": {"repo_grounded": "blocker", "metadata_grounded": "blocker"}
    }
  ],
  "doc_column_verdicts": [
    {
      "doc_path": "docs/orders-guide.md",
      "model": "fct_orders",
      "verdict": "matches|doc_lists_columns_model_lacks|partial",
      "offending_columns": ["order_total"]
    }
  ],
  "doc_classifications": [
    {"path": "docs/glossary.md", "doc_type": "glossary"}
  ],
  "rows_in": {"multi_home": 0, "doc_column_claims": 0, "doc_classification": 0},
  "rows_dropped_by_cap": {"multi_home": 0, "doc_column_claims": 0, "doc_classification": 0}
}
```

Carry `is_dbt_identifier`, `authoritative_definition_exists`, and
`severity_if_differ` through verbatim from the input row so synthesis can apply
the conditional reliability rule without re-reading the scan JSON. (Subagent F
only ever receives no-fallback candidates, so their `severity_if_differ` is
`blocker` for both archetypes; dbt-pinned candidates are adjudicated inline in
synthesis, not here.) Echo `dropped_beyond_cap` into `rows_dropped_by_cap`.

## Calibration

- Default to `agree` / `matches` when snippets are consistent. Only `differ`
  when you can name the inconsistency.
- A vague doc is not a contradiction. Silence in one home is not disagreement.
- A bare identifier-name match is `can_t_tell`, not `differ`. A short or common
  name (`email`, `stage`, `status`, `mode`) appearing in an unrelated context (a
  different table, an infra or admin runbook, a generic code-terminology note) is
  a homonym, not the same object defined two ways. Only `differ` when the doc
  defines the SAME object the dbt layer defines.
- Never invent an identifier, column, or doc path not present in the input.
