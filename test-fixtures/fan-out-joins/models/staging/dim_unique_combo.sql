-- Unique on the (region_id, day) tuple via dbt_utils.unique_combination_of_columns.
select
    1 as region_id,
    1 as day,
    'region/day label' as label
