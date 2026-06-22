select
    revenue_date,
    revenue_amount
from {{ ref('fct_orders') }}
