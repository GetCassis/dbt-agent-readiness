# dbt-agent-readiness: messy_jaffle_shop

**Scanned:** 10 models | **Date:** 2026-04-20
**Source:** YAML + raw SQL (manifest not compiled — phantom-column findings flagged provisional)

> This is the output of running the skill against the bundled [`test-fixtures/messy-jaffle-shop`](../test-fixtures/messy-jaffle-shop) project. Use it to see what an audit report looks like before installing.

## Readiness verdict

**Posture:** Not ready for self-serve.
**Distance to ready:** Afternoon of doc fixes + a sprint for grain declarations and tests.
**Confidence:** High.

**In plain terms:** The project is small and cleanly laid out, but an agent pointed at it today will make three concrete mistakes: it will join customers incorrectly because the same entity is named `customer_id`, `cust_id`, and `user_id` across models; it will produce different revenue numbers depending on whether it picks `fct_revenue` or `rpt_daily_revenue` (two models with ambiguous grain built from the same source); and it will SELECT a column that doesn't exist (`customers.loyalty_tier` is documented in YAML but the SQL uses `SELECT *` from a staging model that doesn't emit it — a macro-resolution ambiguity). Description coverage is 46.5% raw, but only 25.6% of columns carry trustworthy descriptions — more than half of the "documented" columns are placeholder restatements ("Customer ID", "The amount", "Primary key").

## Blockers (agent will hit these today)

### 1. The same entity is named three different ways across models

**What the agent gets wrong:** Asked "how many orders did customer X place?", the agent joins `orders.customer_id` to `customers.customer_id` and misses the rows in `fct_revenue` where the column is `cust_id`. Or filters `WHERE user_id = X` on a staging model where the same concept is `customer_id`.
**Evidence:** `catalogs.concept_variants` cluster `customer_id` has distinct names `['cust_id', 'customer_id', 'user_id']`. [models/marts/fct_revenue.sql:13](../test-fixtures/messy-jaffle-shop/models/marts/fct_revenue.sql#L13) emits `o.cust_id`. [models/marts/customers.sql:11](../test-fixtures/messy-jaffle-shop/models/marts/customers.sql#L11) aliases `o.cust_id as customer_id`. Staging uses `user_id` in `stg_customer_events`.
**Affected models:** `customers`, `orders`, `fct_revenue`, `int_customer_orders`, `stg_customer_events`.
**Blast radius:** Every cross-model customer question.
**Fix:** Rename to one canonical form (`customer_id`). Single find-replace pass + test updates.
**Fix type:** naming.
**Effort:** afternoon.

### 2. Two revenue marts, both with ambiguous grain

**What the agent gets wrong:** Asked "what was revenue last week?", the agent picks `fct_revenue` or `rpt_daily_revenue` at random. `fct_revenue` groups by `(order_date, cust_id, has_refund)` — one row per customer per day per refund-status. `rpt_daily_revenue` groups by `revenue_date` only — one row per day. SUM(total_revenue) on either works but "average revenue per row" gives wildly different answers.
**Evidence:** Review queue flagged `grain_ambiguous` (severity high) on both models. [models/marts/fct_revenue.sql:23](../test-fixtures/messy-jaffle-shop/models/marts/fct_revenue.sql#L23) groups by three columns but no description declares the grain. [models/marts/rpt_daily_revenue.sql](../test-fixtures/messy-jaffle-shop/models/marts/rpt_daily_revenue.sql) same pattern.
**Affected models:** `fct_revenue`, `rpt_daily_revenue`.
**Blast radius:** Every revenue question.
**Fix:** Add `Scope:` + `Grain:` lines to both YAML descriptions. Decide which is canonical and cross-reference from the other.
**Fix type:** doc_only + semantic_layer_decision.
**Effort:** afternoon.

### 3. Description coverage is half as trustworthy as it looks

**What the agent gets wrong:** Reads "Primary key" on `customers.customer_id` and gets no information about what a customer actually is. Reads "The amount" on `orders.amount` and doesn't know if it's gross, net, in cents, in dollars, or includes refunds.
**Evidence:** `catalogs.effective_description_coverage` reports 11/43 trustworthy (25.6%) vs 20/43 raw (46.5%). Breakdown: 8 weak descriptions, 1 phantom-documented, 0 SQL contradictions. Top offenders: [customers.customer_id = "Primary key"](../test-fixtures/messy-jaffle-shop/models/marts/_marts_schema.yml), [orders.amount = "The amount"](../test-fixtures/messy-jaffle-shop/models/marts/_marts_schema.yml), [orders.order_id = "Order ID"](../test-fixtures/messy-jaffle-shop/models/marts/_marts_schema.yml).
**Affected models:** `customers`, `orders`, all 4 staging models.
**Blast radius:** Any question whose answer depends on measure semantics.
**Fix:** Replace the 8 weak descriptions with ones that say what the entity *is*, not what type the column is.
**Fix type:** doc_only.
**Effort:** afternoon.

### Notes on what did NOT become a Blocker

- **`customers.loyalty_tier` phantom column** — flagged `confidence: provisional` because [models/marts/customers.sql:31](../test-fixtures/messy-jaffle-shop/models/marts/customers.sql#L31) uses `SELECT * from final` and the static analyzer can't resolve whether `loyalty_tier` is in the final CTE's columns. Goes to Hygiene with "re-run with `dbt compile`" as the verification step. If `dbt compile` confirms it's truly missing, promote to Blocker #4.
- **0 relationship tests, 3 models with zero tests** — forecasts, not evidence. Moved to Hygiene with verification queries.

## Hygiene (risk factors — verify before trusting the pilot)

### Verification to-do

| Risk | Model / column | Verification query | If non-zero |
|---|---|---|---|
| Phantom column (provisional) | `customers.loyalty_tier` | `cd test-fixtures/messy-jaffle-shop && dbt compile && grep loyalty_tier target/compiled/...` | promote to Blocker: agent SELECTs a column that doesn't exist |
| Missing PK test | `int_customer_orders.customer_id` (1 inbound ref) | `SELECT customer_id, COUNT(*) FROM int_customer_orders GROUP BY 1 HAVING COUNT(*) > 1` | promote: fan-out on join to `customers` |
| Missing PK test | `fct_revenue` (composite grain) | `SELECT order_date, cust_id, has_refund, COUNT(*) FROM fct_revenue GROUP BY 1,2,3 HAVING COUNT(*) > 1` | promote: revenue double-counted |
| Missing relationships | `orders.customer_id` → `customers.customer_id` | `SELECT COUNT(*) FROM orders a LEFT JOIN customers b ON a.customer_id=b.customer_id WHERE b.customer_id IS NULL AND a.customer_id IS NOT NULL` | promote: orphan orders, LEFT JOIN returns nulls agent won't expect |
| Missing `accepted_values` | `orders.status`, `stg_orders.status`, `customers.loyalty_tier` | `SELECT DISTINCT status FROM orders` — compare against docs | promote if undocumented values exist |

### Standing hygiene items (don't block pilot, keep on backlog)

- **Grain undeclared** on 3/4 core models. The description of `fct_revenue` and `rpt_daily_revenue` is also silent on cardinality (see Blocker #2) — those two are promoted. `customers` and `orders` have grain clear enough from context.
- **Models with zero tests** (3): `int_customer_orders`, `int_order_payments`, `stg_customer_events`. Listed in appendix.
- **Global test severity:** not set (falls back to dbt default: `error`). No action needed.

## What's safe to start with

### Safe today

No models currently meet all safety criteria. The closest candidate is `stg_customers` (has PK test, grain clear from context, no Blocker flags) — safe for simple "how many customers?" questions, but not for anything joining to `orders` until Blocker #1 is resolved.

### Safe after one small fix

| Model | One fix | File |
|---|---|---|
| `orders` | Replace `"The amount"` with "Order total in USD, including tax, after discounts, before refunds" | models/marts/_marts_schema.yml |
| `stg_customers` | Replace `"Primary key"` on `customer_id` with "Unique customer identifier (sourced from raw.customers.id)" | models/staging/_stg_schema.yml |
| `int_customer_orders` | Add `unique` test on `customer_id` | models/intermediate/_int_schema.yml |

### Out of scope until remediation

- Any cross-model customer question (Blocker #1).
- Any revenue question routed through `fct_revenue` vs `rpt_daily_revenue` (Blocker #2).
- Any question selecting `customers.loyalty_tier` until the phantom is confirmed.

## Remediation backlog

### This week (doc/naming fixes)
- Rename `cust_id` / `user_id` → `customer_id` project-wide (find-replace).
- Add `Scope:` + `Grain:` paragraphs to `fct_revenue` and `rpt_daily_revenue`.
- Replace the 8 weak descriptions listed in Appendix.
- Add an `accepted_values` test on `orders.status` and `stg_orders.status` (listing the canonical set).

### This sprint (model + test changes)
- Compile `dbt compile` and re-audit to confirm or dismiss the `customers.loyalty_tier` phantom.
- Add `unique` + `not_null` tests to all FKs.
- Add relationship test on `orders.customer_id` → `customers.customer_id`.

### Later (structural)
- Decide whether `fct_revenue` or `rpt_daily_revenue` is canonical; deprecate the other.

## Coverage snapshot

| Dimension | Score | Detail |
|-----------|-------|--------|
| Concept consistency | poor | 1 concept cluster (`customer_id`/`cust_id`/`user_id`) across 5 models |
| Scope/filter transparency | good | No hidden WHERE clauses detected |
| Description trustworthiness | poor | Effective 25.6% vs raw 46.5% — 9 untrusted of 20 documented |
| Key/entity stability | mixed | Keys named inconsistently; no relationship tests |
| Safe entry points | poor | No mart meets safety criteria today |

### Detailed metrics

| Metric | Score |
|--------|-------|
| Models with descriptions | 6/10 (60%) |
| Columns with descriptions (raw) | 20/43 (46.5%) |
| Columns with trustworthy descriptions (effective) | 11/43 (25.6%) |
| Grain declared (core/ref) | 0/4 (informational) |
| Relationships declared / implicit | 0 / 3 (informational — see Verification to-do) |
| Unique / not_null / accepted_values / relationships tests | 4 / 5 / 1 / 0 |
| Models with zero tests | 3 |

**Why two coverage numbers?** Raw coverage counts any non-empty YAML description. Effective coverage subtracts columns whose descriptions are weak (restate the name or are placeholders), copy-pasted, contradict the SQL, or describe phantom columns. The gap is the share of docs an agent cannot trust.

## What's working well

- Clean three-layer structure (`staging` → `intermediate` → `marts`).
- No broken refs, no lineage cycles, no duplicate YAML columns.
- Every staging model has at least one test.

## Appendix

### Review packet verdicts

| Packet | Verdict | Severity | Summary |
|---|---|---|---|
| customer | confirmed | high | `customer_id` / `cust_id` / `user_id` clusters across 5 models |
| fct_revenue (grain) | confirmed | high | GROUP BY 3 columns, no grain declared |
| rpt_daily_revenue (grain) | confirmed | high | GROUP BY revenue_date, no grain declared |

### Catalogs (non-empty sections)

**Low-quality column descriptions** (8 from `catalogs.weak_column_descriptions`)

| Model | Column | Current text | Reason |
|---|---|---|---|
| customers | customer_id | "Primary key" | generic_technical |
| stg_customers | customer_id | "Primary key" | generic_technical |
| int_customer_orders | customer_id | "Customer ID" | restates_name |
| orders | order_id | "Order ID" | restates_name_or_too_short |
| orders | amount | "The amount" | restates_name |
| stg_orders | order_id | "The ID" | restates_name_or_too_short |
| stg_payments | payment_id | "Payment ID" | restates_name |
| stg_payments | amount | "The amount" | restates_name |

**Same-concept-different-name clusters** (1 from `catalogs.concept_variants`)

- Canonical: `customer_id`. Variants: `cust_id`, `customer_id`, `user_id`.
- Evidence: `cust_id as customer_id` in `customers.sql`; `user_id` in `stg_customer_events`.

**Same name, different grain** (2 from `catalogs.same_name_different_grain`)

| Column | Layers | Examples |
|---|---|---|
| `order_count` | core, intermediate | `customers.order_count`, `int_customer_orders.order_count` |
| `amount` | core, staging | `orders.amount`, `stg_orders.amount`, `stg_payments.amount` |

**Phantom columns by model** (1 from `catalogs.phantom_columns_by_model`)

| Confidence | Model | Count | Phantom columns | Macro signals | YAML path |
|---|---|---|---|---|---|
| provisional | customers | 1 | `loyalty_tier` | select_star | models/marts/_marts_schema.yml |

**Categorical columns with values only in SQL** (via `test_summary.categorical_columns_without_accepted_values`)

| Column | Models |
|---|---|
| status | orders, stg_orders |
| loyalty_tier | customers |

### Hygiene appendix: test gaps

**Models with zero tests** (3): `int_customer_orders`, `int_order_payments`, `stg_customer_events`.

## What this audit cannot detect

- Runtime data quality (null rates, freshness, row counts) — requires executing queries; verification queries in Hygiene cover this.
- Whether `customers.loyalty_tier` is actually emitted by the compiled SQL — requires `dbt compile`.
- Whether a join makes business sense.

## Audit metadata

| Metric | Value |
|--------|-------|
| Total models scanned | 10 |
| Models reviewed by LLM | 10 (inline — subagent threshold is >30 models) |
| Review packets generated | 2 |
| Concept index size | 6 concepts across 10 models |
| Blockers | 3 |
| Hygiene items | 5 |
| Inventory method | script |

---

*Generated by the [dbt-agent-readiness](https://github.com/GetCassis/dbt-agent-readiness) skill for Claude Code.*
*This audit was built by the team at [Cassis](https://getcassis.com), the living context layer between a company's data and its business.*
