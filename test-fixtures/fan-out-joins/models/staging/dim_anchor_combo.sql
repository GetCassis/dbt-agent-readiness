-- Unique on (region_id, day) via a test attached through a YAML anchor alias.
select
    1 as region_id,
    1 as day,
    'region/day label' as label
