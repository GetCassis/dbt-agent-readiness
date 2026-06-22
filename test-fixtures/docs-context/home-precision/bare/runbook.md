# Scheduling runbook

When a new model is productionalized, a `dim_customers` reference is added to the
nightly load. Example query used during setup:

```sql
select customer_id, customer_name
from dim_customers
where signup_date > '2020-01-01'
```

## Onboarding checklist

| Task | Owner |
|---|---|
| Register dim_customers in the sheetload config | data-eng |

### Terminology

- `dim_customers`: the table the scheduler reads from.
