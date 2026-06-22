{% set payment_methods = ['credit_card', 'coupon'] %}

with order_payments as (

    select
        order_id,

        {% for pm in payment_methods -%}
        sum(case when payment_method = '{{ pm }}' then amount else 0 end) as {{ pm }}_amount,
        {% endfor -%}

        sum(amount) as total_amount

    from {{ ref('stg_payments') }}

    group by order_id

)

select
    order_id,
    {% for pm in payment_methods -%}
    {{ pm }}_amount,
    {% endfor -%}
    total_amount
from order_payments
