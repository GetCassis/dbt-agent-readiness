with base as (
    select id, tags_csv from {{ ref('up_tags') }}
),
split_tags as (
    select id, value as tag
    from base, lateral split_to_table(base.tags_csv, ',')
)
select id, tag from split_tags
