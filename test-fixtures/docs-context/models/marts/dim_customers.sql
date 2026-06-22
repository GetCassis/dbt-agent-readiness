select
    customer_id,
    customer_name,
    customer_email,
    signup_date
from {{ ref('stg_customers') }}
