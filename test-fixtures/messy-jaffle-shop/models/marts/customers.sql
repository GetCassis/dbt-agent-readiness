with customers as (
    select * from {{ ref('stg_customers') }}
),

customer_orders as (
    select * from {{ ref('int_customer_orders') }}
),

customer_payments as (
    select
        o.cust_id as customer_id,
        sum(p.total_amount) as customer_lifetime_value
    from {{ ref('stg_orders') }} o
    left join {{ ref('int_order_payments') }} p on o.order_id = p.order_id
    group by o.cust_id
),

final as (
    select
        c.customer_id,
        c.first_name,
        c.last_name,
        c.signup_date,
        co.first_order_date,
        co.last_order_at as most_recent_order,
        co.order_count as number_of_orders,
        cp.customer_lifetime_value
    from customers c
    left join customer_orders co on c.customer_id = co.customer_id
    left join customer_payments cp on c.customer_id = cp.customer_id
)

select * from final
