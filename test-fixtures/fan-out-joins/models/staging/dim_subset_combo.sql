-- Unique on (region_id, day), but downstreams join on region_id alone.
select
    1 as region_id,
    1 as day,
    'region/day label' as label
