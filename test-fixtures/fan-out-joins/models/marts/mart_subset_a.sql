select e.event_id, d.label
from {{ ref('stg_events') }} as e
left join {{ ref('dim_subset_combo') }} as d
    on e.region_id = d.region_id
