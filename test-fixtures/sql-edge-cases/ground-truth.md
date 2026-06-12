# sql-edge-cases: ground truth

A focused fixture for the `undefined_column_refs` check. Each model exercises
one SQL construct that the static parser used to misread as an undefined
column. Pinned dialect: Snowflake (see `profiles.yml`).

## Upstream models (concrete shapes)

| Model | Columns |
|---|---|
| `up_events` | id, created_at, amount |
| `up_quarters` | id, q1_sales, q2_sales, q3_sales |
| `up_tags` | id, tags_csv |
| `up_raw` | id, name, status |

## Expected `undefined_column_refs`

Exactly two rows must fire, both genuine:

| Model | Column | Why it is real |
|---|---|---|
| `undefined_true_positive` | `nonexistent_column` | Referenced in SELECT, produced by no input relation. |
| `unpivot_true_positive` | `bogus_total` | Referenced alongside a valid UNPIVOT; not a value/name output nor an input column. |

`unpivot_true_positive` must flag `bogus_total` only. Its `period` and
`sales_amount` are the UNPIVOT name/value outputs and are valid.

## Must produce NO finding (the blind spots being fixed)

| Model | Construct |
|---|---|
| `date_parts_ok` | `DATEADD`/`DATEDIFF`/`DATE_TRUNC` date-part tokens (day, month, quarter, minute) parse as pseudo-columns. |
| `unpivot_ok` | `UNPIVOT(sales_amount FOR period IN (...))` value + name columns. |
| `fill_staging_ok` | `fivetran_utils.fill_staging_columns` injects a column set the static parser cannot see. |
| `lateral_ok` | `LATERAL SPLIT_TO_TABLE(...)` exposes a system `value` column. |
