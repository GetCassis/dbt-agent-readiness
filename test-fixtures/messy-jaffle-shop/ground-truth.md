# Messy-jaffle-shop: ground truth

Every intentional issue planted in this fixture, with its exact location.
Use this to validate the dbt-agent-readiness skill: every issue should be found, no extras hallucinated.

## Models inventory

- **10 SQL models**: stg_customers, stg_orders, stg_payments, stg_customer_events, int_order_payments, int_customer_orders, customers, orders, fct_revenue, rpt_daily_revenue
- **3 YAML schema files**: _stg_schema.yml, _int_schema.yml, _marts_schema.yml
- **1 sources definition** in _stg_schema.yml

---

## Description coverage issues

### Models without YAML schema entries

| # | Model | File | Issue |
|---|-------|------|-------|
| D1 | `stg_customer_events` | `models/staging/stg_customer_events.sql` | No YAML entry at all. 5 columns completely undocumented. |
| D2 | `int_order_payments` | `models/intermediate/int_order_payments.sql` | No YAML entry. 6 columns undocumented. Referenced by `customers` and `orders`. |
| D3 | `rpt_daily_revenue` | `models/marts/rpt_daily_revenue.sql` | No YAML entry. 7 columns undocumented. Downstream reporting model. |

### Missing column descriptions (in documented models)

| # | Model | Column | File |
|---|-------|--------|------|
| D4 | `stg_orders` | `order_date` | `_stg_schema.yml` — no description |
| D5 | `stg_orders` | `status` | `_stg_schema.yml` — no description |
| D6 | `stg_orders` | `is_completed` | `_stg_schema.yml` — no description |
| D7 | `stg_payments` | `order_id` | `_stg_schema.yml` — no description |
| D8 | `customers` | `first_name` | `_marts_schema.yml` — no description |
| D9 | `customers` | `last_name` | `_marts_schema.yml` — no description |
| D10 | `customers` | `most_recent_order` | `_marts_schema.yml` — no description |
| D11 | `orders` | `order_date` | `_marts_schema.yml` — no description |
| D12 | `orders` | `payment_count` | `_marts_schema.yml` — no description |
| D13 | `orders` | `payment_method_count` | `_marts_schema.yml` — no description |
| D14 | `fct_revenue` | ALL columns | `_marts_schema.yml` — fct_revenue has zero descriptions for any column |
| D15 | `int_customer_orders` | `order_count` | `_int_schema.yml` — no description |
| D16 | `int_customer_orders` | `completed_order_count` | `_int_schema.yml` — no description |

### Low-quality descriptions

| # | Model | Column | Description | Issue |
|---|-------|--------|-------------|-------|
| D17 | `stg_orders` | `order_id` | "The ID" | Restates column name, adds no value |
| D18 | `orders` | `amount` | "The amount" | Restates column name, adds no value |
| D19 | `orders` | `order_id` | "Order ID" | Restates column name |
| D20 | `stg_customers` | `customer_id` | "Primary key" | Too generic, doesn't describe the business concept |
| D21 | `stg_payments` | `payment_id` | "Payment ID" | Restates column name |

### Model without description

| # | Model | File | Issue |
|---|-------|------|-------|
| D22 | `fct_revenue` | `_marts_schema.yml` | No model-level description |

---

## Naming consistency issues

### Same-concept-different-name (customer identifier)

| # | Model | Column name | Issue |
|---|-------|-------------|-------|
| N1 | `stg_customers` | `customer_id` | Standard name |
| N2 | `stg_orders` | `cust_id` | Abbreviation variant |
| N3 | `stg_customer_events` | `user_id` | Different concept name entirely |
| N4 | `fct_revenue` | `cust_id` | Abbreviation variant |
| N5 | `int_customer_orders` | `customer_id` | Standard name |
| N6 | `customers` | `customer_id` | Standard name |
| N7 | `orders` | `customer_id` | Standard name (aliased from cust_id in SQL) |

All refer to the same business concept but use 3 different names: `customer_id`, `cust_id`, `user_id`.

### Convention violations: model naming

| # | Issue |
|---|-------|
| N8 | `fct_revenue` uses `fct_` prefix but `customers` and `orders` in the same directory have no prefix. Inconsistent mart-layer naming convention. |

### Convention violations: date/timestamp suffixes

| # | Model | Columns | Issue |
|---|-------|---------|-------|
| N9 | `int_customer_orders` | `first_order_date` vs `last_order_at` | Mixed `_date` and `_at` suffixes for temporal columns in the same model |
| N10 | `stg_customers` | `signup_date` | Uses `_date` |
| N11 | `stg_customer_events` | `event_timestamp` | Uses `_timestamp` — a third convention |

### Convention violations: boolean prefixes

| # | Model | Columns | Issue |
|---|-------|---------|-------|
| N12 | `stg_orders` | `is_completed` | Uses `is_` prefix |
| N13 | `stg_customer_events` | `has_converted` | Uses `has_` prefix |
| N14 | `fct_revenue` | `has_refund` | Uses `has_` prefix |

Mixed `is_` and `has_` for booleans. While semantically different, inconsistency within a project is a signal.

### Same column name, ambiguous meaning

| # | Column | Models | Issue |
|---|--------|--------|-------|
| N15 | `amount` | `stg_payments.amount` (per-payment USD), `orders.amount` (total order USD) | Same name, different granularity. An agent would not know which to use for "revenue." |
| N16 | `order_count` | `int_customer_orders.order_count`, `fct_revenue.order_count`, `rpt_daily_revenue.daily_orders` | Same concept with different names and granularity across models |

---

## Join path clarity issues

### Missing relationship tests

| # | Model | Column | Refs to | Issue |
|---|-------|--------|---------|-------|
| J1 | `stg_orders` | `cust_id` | `stg_customers.customer_id` | No `relationships` test declared, and the name mismatch (`cust_id` vs `customer_id`) makes the implicit join even harder for an agent to discover |
| J2 | `stg_payments` | `order_id` | `stg_orders.order_id` | Has `not_null` test but no `relationships` test |
| J3 | `int_order_payments` | `order_id` | `stg_payments.order_id` | No YAML entry at all, so no relationship test possible |
| J4 | `int_customer_orders` | `customer_id` | `stg_orders.cust_id` | No relationship test; also the join involves a name mismatch (customer_id vs cust_id) |

### Missing primary key tests

| # | Model | Expected PK | Issue |
|---|-------|-------------|-------|
| J5 | `orders` | `order_id` | No `unique` or `not_null` tests |
| J6 | `fct_revenue` | composite (`revenue_date`, `cust_id`) | No PK tests at all. No tests of any kind. |
| J7 | `rpt_daily_revenue` | `revenue_date` | No YAML at all |
| J8 | `int_order_payments` | `order_id` | No YAML at all |

### ref() without declared relationships

| # | SQL file | ref() | Issue |
|---|----------|-------|-------|
| J9 | `customers.sql` | `ref('stg_orders')` | refs stg_orders but there's no relationship test connecting these models |
| J10 | `customers.sql` | `ref('int_order_payments')` | refs a model that has no YAML entry at all |
| J11 | `fct_revenue.sql` | `ref('stg_orders')` | No relationship declared |
| J12 | `rpt_daily_revenue.sql` | `ref('fct_revenue')` | Neither model has relationship tests |

---

## Test coverage issues

### Models with zero tests

| # | Model | Issue |
|---|-------|-------|
| T1 | `fct_revenue` | Has YAML entry but zero tests on any column |
| T2 | `orders` | Has YAML entry but zero tests on any column |
| T3 | `int_order_payments` | No YAML entry, so no tests |
| T4 | `stg_customer_events` | No YAML entry, so no tests |
| T5 | `rpt_daily_revenue` | No YAML entry, so no tests |
| T6 | `int_customer_orders` | Has YAML entry but zero tests |

### Categoricals without accepted_values tests

| # | Model | Column | Issue |
|---|-------|--------|-------|
| T7 | `stg_orders` | `status` | No `accepted_values` test (stg_payments.payment_method has one, inconsistent) |

---

## Documentation-to-schema drift (stale YAML)

| # | Model | Issue |
|---|-------|-------|
| S1 | `customers` | YAML documents a `loyalty_tier` column that does not exist in the SQL model |

---

## SQL logic issues (bonus tier)

These issues are not intentionally planted but are genuine bugs/risks present in the fixture. They should be counted as true positives if found.

| # | Issue | File | Detail |
|---|-------|------|--------|
| X1 | `fct_revenue.has_refund` broken SQL reference | `models/marts/fct_revenue.sql` | `has_refund` appears in SELECT and GROUP BY but is not defined in any CTE or source table. Query would fail to build. |
| X2 | `rpt_daily_revenue` self-referencing alias | `models/marts/rpt_daily_revenue.sql` | SQL references aliases defined in the same SELECT statement. Fails on most warehouses. |
| X3 | Model overlap clusters (revenue question) | Multiple | fct_revenue, orders, and rpt_daily_revenue can all answer "what is our revenue?" with no disambiguation |
| X4 | Fan-out risk on `int_order_payments` joins | `int_order_payments` -> `customers`, `orders` | No unique test on join column, two downstream models join to it |
| X5 | Source `raw_refunds` orphaned | `_stg_schema.yml` | Source defined but not referenced by any model |
| X6 | `int_customer_orders.last_order_at` timestamp vs date | `_int_schema.yml` | Column name uses `_at` (implying timestamp) but SQL produces a date | 3/3 runs |
| X7 | `stg_payments.amount` unit contradiction | `_stg_schema.yml` vs SQL | Model description says "cents" but column description says "USD" (converted from cents) | 3/3 runs |
| X8 | Abbreviation inconsistency (cc vs full forms) | Multiple | `cc_revenue` vs `credit_card` in descriptions | 3/3 runs |
| X9 | `customers` LEFT JOIN without COALESCE | `models/marts/customers.sql` | LEFT JOIN to int_order_payments, NULLs propagate silently to order_count, amount | 2/3 runs |

---

## Summary counts

| Category | Count |
|----------|-------|
| Models without YAML | 3 |
| Columns missing descriptions | ~25+ |
| Low-quality descriptions | 5 |
| Naming inconsistencies | 16 |
| Missing relationship tests | 4 |
| Missing PK tests | 4 |
| Models with zero tests | 6 |
| Stale YAML (phantom column) | 1 |
| ref() without relationship | 4 |
| SQL logic issues (bonus) | 9 |
| **Total** | **67** |
