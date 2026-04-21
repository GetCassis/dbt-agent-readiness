-- NO YAML SCHEMA for this model (intentional gap)
-- This is a heavily-referenced reporting model with no documentation
with revenue as (
    select * from {{ ref('fct_revenue') }}
),

daily as (
    select
        revenue_date,
        sum(total_revenue) as daily_revenue,
        sum(transaction_count) as daily_transactions,
        sum(order_count) as daily_orders,
        count(distinct cust_id) as unique_customers,
        sum(cc_revenue) as daily_cc_revenue,
        sum(gift_card_revenue) as daily_gc_revenue,
        daily_revenue - daily_cc_revenue - daily_gc_revenue as daily_other_revenue
    from revenue
    group by revenue_date
)

select * from daily
