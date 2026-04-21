-- NO YAML SCHEMA for this model (intentional gap)
with payments as (
    select * from {{ ref('stg_payments') }}
),

aggregated as (
    select
        order_id,
        sum(amount) as total_amount,
        count(*) as payment_count,
        min(amount) as min_payment,
        max(amount) as max_payment,
        count(distinct payment_method) as payment_method_count
    from payments
    group by order_id
)

select * from aggregated
