with base as (
    select * from {{ ref('up_raw') }}
),
fields as (
    select
        {{ fivetran_utils.fill_staging_columns(
            source_columns=adapter.get_columns_in_relation(ref('up_raw')),
            staging_columns=get_raw_columns()
        ) }}
    from base
)
select id, name, status from fields
