with source as (
    select * from {{ source('jaffle_shop', 'raw_orders') }}
),

renamed as (
    select
        id as order_id,
        user_id as cust_id,
        order_date,
        status,
        is_completed
    from source
)

select * from renamed
