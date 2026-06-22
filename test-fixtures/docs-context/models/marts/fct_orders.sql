select
    order_id,
    customer_id,
    order_amount,
    order_status
from {{ ref('stg_customers') }}
