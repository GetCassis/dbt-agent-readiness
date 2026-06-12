select e.note, d.label
from {{ ref('stg_events') }} as e
left join {{ ref('dim_no_test') }} as d
    on e.region_id = d.region_id
