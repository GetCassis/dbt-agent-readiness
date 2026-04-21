with source as (
    select * from {{ source('jaffle_shop', 'raw_customers') }}
),

renamed as (
    select
        id as customer_id,
        first_name,
        last_name,
        created_at as signup_date
    from source
)

select * from renamed
