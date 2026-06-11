with base as (
    select id, created_at, amount from {{ ref('up_events') }}
)
select
    id,
    date_trunc(month, created_at)                      as month_start,
    dateadd(day, -7, created_at)                       as week_ago,
    datediff(minute, created_at, current_timestamp())  as age_minutes,
    date_trunc(quarter, created_at)                    as quarter_start,
    amount
from base
