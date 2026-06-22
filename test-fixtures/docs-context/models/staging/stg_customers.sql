select
    customer_id,
    customer_name,
    customer_email,
    signup_date
from {{ source('raw', 'customer_events') }}
