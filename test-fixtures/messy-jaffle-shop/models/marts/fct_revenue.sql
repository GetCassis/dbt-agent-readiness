-- Uses different naming convention (fct_ prefix) from other mart models
with payments as (
    select * from {{ ref('stg_payments') }}
),

orders as (
    select * from {{ ref('stg_orders') }}
),

final as (
    select
        o.order_date as revenue_date,
        o.cust_id,
        sum(p.amount) as total_revenue,
        count(distinct p.payment_id) as transaction_count,
        count(distinct o.order_id) as order_count,
        sum(case when p.payment_method = 'credit_card' then p.amount else 0 end) as cc_revenue,
        sum(case when p.payment_method = 'gift_card' then p.amount else 0 end) as gift_card_revenue,
        sum(case when p.payment_method = 'coupon' then p.amount else 0 end) as coupon_amount,
        has_refund
    from orders o
    left join payments p on o.order_id = p.order_id
    group by o.order_date, o.cust_id, has_refund
)

select * from final
