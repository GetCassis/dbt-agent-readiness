# fan-out-joins: ground truth

A focused fixture for the `fan_out_joins` check and its uniqueness-coverage
logic. Each dimension is joined by two downstream marts; what differs is
whether a uniqueness guarantee covers the join key. Pinned dialect: Snowflake
(see `profiles.yml`).

## Dimensions and how they are joined

| Dimension | Uniqueness declared | Downstreams join on | Covered? |
|---|---|---|---|
| `dim_unique_combo` | `unique_combination_of_columns(region_id, day)` (classic syntax) | `(region_id, day)` | yes, full tuple |
| `dim_anchor_combo` | same tuple, attached via YAML anchor alias `*combo_tests` (`arguments:` syntax) | `(region_id, day)` | yes, full tuple |
| `dim_subset_combo` | `unique_combination_of_columns(region_id, day)` | `region_id` only | no, strict subset |
| `dim_no_test` | none | `region_id` | no, no guarantee |

`dim_anchor_source` defines the anchor and is not joined by anything.

## Expected `fan_out_joins`

Exactly two rows must fire, both genuine:

| Model | Column | Why it is real |
|---|---|---|
| `dim_subset_combo` | `region_id` | The uniqueness guarantee is on the `(region_id, day)` tuple; joining on `region_id` alone can still fan out. |
| `dim_no_test` | `region_id` | No uniqueness guarantee on the join key at all. |

## Must produce NO finding (uniqueness covers the join)

| Model | Why suppressed |
|---|---|
| `dim_unique_combo` | Join key set `(region_id, day)` matches the unique tuple. |
| `dim_anchor_combo` | Same, with the test reached through a YAML anchor alias. |
