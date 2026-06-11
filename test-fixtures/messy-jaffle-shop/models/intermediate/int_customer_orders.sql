with orders as (
    select * from {{ ref('stg_orders') }}
),

aggregated as (
    select
        cust_id as customer_id,
        min(order_date) as first_order_date,
        max(order_date) as last_order_at,
        count(*) as order_count,
        count(case when is_completed then 1 end) as completed_order_count
    from orders
    group by cust_id
)

select * from aggregated
