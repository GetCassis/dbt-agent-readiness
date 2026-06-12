with base as (
    select id, amount from {{ ref('up_events') }}
)
select id, amount, nonexistent_column
from base
