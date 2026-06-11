with orders as (
    select * from {{ ref('stg_orders') }}
),

payments as (
    select * from {{ ref('int_order_payments') }}
),

final as (
    select
        o.order_id,
        o.cust_id as customer_id,
        o.order_date,
        o.status,
        p.total_amount as amount,
        p.payment_count,
        p.payment_method_count
    from orders o
    left join payments p on o.order_id = p.order_id
)

select * from final
