# Orders guide

How the orders mart is built and what each field means.

## fct_orders

| Column | Meaning |
|---|---|
| order_id | Order surrogate key |
| customer_id | Customer reference |
| order_total | Total value of the order |
| order_status | Lifecycle status |

Note: the `order_total` field is described here but the model actually emits
`order_amount`. This is a deliberate doc-vs-code drift.
