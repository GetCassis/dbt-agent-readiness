# Ground truth — docs-context fixture

Planted signals the docs scan (v1.4.0) must reproduce. The deterministic gate
asserts Layer-1 detection only; the agree/differ verdict on doc-vs-doc
disagreements is the Layer-2 LLM's job and is out of scope for the committed
test.

Run the external docs through the scanner with `--doc-sources docs` and
`--today 2026-06-19`.

## dbt layer (4 models, 2 source tables)

| Model | Description | Note |
|---|---|---|
| `stg_customers` | none | from `raw.customer_events`; never mentioned in any doc |
| `dim_customers` | good ("one row per customer …") | authoritative dbt definition exists |
| `fct_orders` | good ("one row per order …") | emits `order_amount`, not `order_total` |
| `fct_revenue` | **none** | no authoritative dbt definition — the reliability fallback is absent |

## Planted findings

1. **Correct doc, no false drift.** `docs/customers.md` documents `dim_customers`
   with its real columns. Must be matched (coverage = documented) and produce
   **no** column drift.
2. **doc-vs-code drift.** `docs/orders-guide.md` lists `order_total` under a
   `fct_orders` heading. The model emits `order_amount`. `column_drift` must flag
   `order_total` for `fct_orders` at `confidence: high` (model YAML mirrors SQL).
3. **Multi-home, no fallback → Blocker-eligible.** `fct_revenue` is defined two
   different ways in `docs/glossary.md` (gross incl. refunds) and
   `docs/finance-notes.md` (net after refunds). It is a dbt identifier with **no**
   authoritative dbt definition. `multi_home_candidates` must carry it with
   `is_dbt_identifier: true`, `authoritative_dbt_definition.exists: false`,
   `doc_count: 2`. Under the reliability rule this is a Blocker.
4. **Multi-home, with fallback → Hygiene/context.** `dim_customers` is mentioned
   in two docs but the dbt layer pins it (good description). It must appear as a
   candidate with `authoritative_dbt_definition.exists: true`. Under the rule the
   agent can answer reliably from dbt, so this is Hygiene/context, not a Blocker.
5. **Off-repo authority.** `docs/legacy-pipeline.md` links a Google Doc and a
   Confluence wiki and says "single source of truth." `external_pointers` must
   count `google_docs` and `confluence`, and the doc must appear in
   `defers_authority_offsite_docs`.
6. **Staleness.** `docs/legacy-pipeline.md` is marked deprecated and dated 2021.
   `staleness_flags` must flag it with a `deprecated` marker and `stale_by_date`.
7. **Coverage gap.** `stg_customers`, `customer_events`, `order_events` are
   documented nowhere. `identifier_coverage.undocumented_list` must list them;
   `documented_list` must list `dim_customers`.

## dbt-layer boundary

`models/README.md` and `models/_models_docs.md` (a `{% docs %}` block file) live
inside the model path. Under auto-discovery they must be excluded from the
external corpus (`dbt_layer_excluded >= 2`), never scanned as prose.

## Home precision (docs_scan 1.5)

A doc *homes* an identifier only in a definitional context (heading subject,
column-dictionary row key, "`x` is/means …" prose, or a glossary entry). A bare
reference does not. Two planted dirs prove this, scanned with `--doc-sources`:

- `home-precision/bare/runbook.md` mentions `dim_customers` only in bare
  contexts — a fenced SQL query, a checklist table cell, and a code-terminology
  colon-list. `dim_customers` must be *mentioned* but must NOT home, so it is
  NOT a `multi_home_candidate` even though the dbt layer pins it.
- `home-precision/real/glossary.md` defines `dim_customers` in a glossary entry.
  It homes, so `dim_customers` IS a `multi_home_candidate` (one doc home + the
  authoritative dbt definition).
