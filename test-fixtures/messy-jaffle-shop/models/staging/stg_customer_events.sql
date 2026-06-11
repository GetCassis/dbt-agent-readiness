-- NO YAML SCHEMA for this model (intentional gap)
with source as (
    select * from {{ source('jaffle_shop', 'raw_customer_events') }}
),

renamed as (
    select
        id as event_id,
        user_id,
        event_type,
        event_timestamp,
        has_converted
    from source
)

select * from renamed
