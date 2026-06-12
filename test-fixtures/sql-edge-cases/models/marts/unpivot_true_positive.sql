with metrics as (
    select id, q1_sales, q2_sales from {{ ref('up_quarters') }}
)
select id, period, sales_amount, bogus_total
from metrics
unpivot(sales_amount for period in (q1_sales, q2_sales))
