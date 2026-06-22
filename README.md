# dbt-agent-readiness

A Claude Code skill that audits a dbt project for what an AI agent will get wrong if you point it at the data today: wrong metric, wrong table, missed rows, broken joins.

Built for dbt teams piloting AI analysts, copilots, or internal data agents.

## What it catches

**Blockers** (code evidence, agent will hit today):
- Two models claim to represent revenue but calculate it differently
- The same entity is named `customer_id`, `cust_id`, and `user_id` across models
- A YAML-declared column the SQL doesn't actually emit (agent SELECTs a column that doesn't exist)
- A model description promises totality but the SQL filters rows
- One `entity_id` column refers to different entities across models
- Description says COUNT, SQL does SUM
- `ref()` to a model that doesn't exist (queries fail at compile)
- Unit drift (EUR / EUR cents, Wh / kWh)
- Within-model concept collision (`deployment_start_date` + `zone_deployment_start_date`)

**Hygiene** (risk factors, each shipped with a SQL query you can run to verify):
- Missing PK / not-null / relationship / accepted_values tests
- Grain undeclared when the description is also silent on cardinality
- Macro-using models flagged for `dbt compile` when the manifest is missing

**Optional docs mode** (context outside the dbt layer):
- A doc defines a term one way and another doc defines it differently, with no authoritative dbt definition to settle it (Blocker)
- A doc claims a model has a column it does not emit (Blocker when the model's YAML mirrors its SQL)
- Models documented in prose vs models documented nowhere (coverage gap)
- Docs pointing off-repo at Google Docs / Confluence / Notion / Slack an agent cannot read
- Stale docs (deprecated markers, years-old dates)

## Sample output

A Blocker from the bundled sample report:

```
### 1. The same entity is named three different ways across models

What the agent gets wrong: Asked "how many orders did customer X place?",
the agent joins orders.customer_id to customers.customer_id and misses
the rows in fct_revenue where the column is cust_id.

Evidence: catalogs.concept_variants cluster customer_id has distinct
names ['cust_id', 'customer_id', 'user_id'].
models/marts/fct_revenue.sql:13 emits o.cust_id.
models/marts/customers.sql:11 aliases o.cust_id as customer_id.

Fix: Rename to one canonical form (customer_id).
Effort: afternoon.
```

See the [full sample report](examples/messy-jaffle-shop-audit.md) generated against the bundled test fixture.

## Setup

Clone into your Claude Code skills directory:

```bash
git clone https://github.com/GetCassis/dbt-agent-readiness ~/.claude/skills/dbt-agent-readiness
```

Install Python dependencies:

```bash
pip install -r ~/.claude/skills/dbt-agent-readiness/requirements.txt
```

**Requirements:**
- Claude Code (any recent version with Skills support)
- Python 3.8+
- `pyyaml` and [`sqlglot`](https://github.com/tobymao/sqlglot) (installed via `requirements.txt`)

**Recommended:** run `dbt compile` in the target project before auditing so the skill can resolve macros (`dbt_utils.star`, `SELECT *`). Without it, phantom-column findings on macro-using models are suppressed rather than emitted.

## Run the audit

In Claude Code:

```
Run the dbt-agent-readiness skill on /path/to/dbt/project
```

The report is written to `{project_path}/dbt-agent-readiness.md`.

### Optional: scan docs outside the dbt layer

The audit is dbt-only by default. To also map the documentation that lives
outside the dbt layer (repo `docs/`, runbooks, READMEs, a dropped `.md`), opt in:

```
Run dbt-agent-readiness on /path/to/dbt/project and include the docs
```

If your dbt project sits in a subdirectory of a larger repo, point it at the
repo's documentation explicitly so docs above the project are included:

```
Run dbt-agent-readiness on ./transform/analytics and scan the docs in ./docs
```

Docs mode reports where context lives, where it duplicates the dbt layer, where
a doc claims columns a model does not emit, where definitions disagree with no
authoritative dbt fallback (those become Blockers), where docs go stale, and
where they point off-repo at sources an agent cannot read (Google Docs,
Confluence, Notion, Slack). It is deterministic-first: no documentation prose is
sent to the model except short flagged snippets, so cost scales with findings,
not doc volume.

## What the report contains

1. **Readiness verdict**: ready / not ready / unsafe, with distance to ready.
2. **Blockers**: evidence-backed failures an agent will hit today, each with affected models, blast radius, fix, and effort estimate.
3. **Hygiene**: risk factors, each with a verification query you can run to promote or dismiss.
4. **Safe starting perimeter**: which models an agent can query safely today.
5. **Remediation backlog**: prioritized list of fixes.

## Scales to project size

- ≤30 models: inline analysis
- 31 to 200 models: 3 to 4 parallel subagents (flag-driven review + per-model deep pass)
- \>200 models: checkpoint before spawning subagents

## Data handling

The skill reads your dbt project files locally (SQL, YAML, descriptions, optionally `target/manifest.json`). Claude Code, running in your session, sends that content to Anthropic as part of its normal operation. The skill itself does not open network connections, does not query your warehouse, and does not require warehouse credentials. It writes a single report file to `{project_path}/dbt-agent-readiness.md` and modifies nothing else in your project.

## What this audit cannot detect

- Runtime data quality (null rates, freshness, row counts). Hygiene items carry verification queries you can run against the warehouse.
- Source system changes. Only runtime monitoring catches upstream format drift.
- Whether a join makes business sense. The audit sees structure, not domain validity.
- Query patterns and usage frequency. Would require query logs.
- BI tool metric conflicts. Would require Looker / Tableau export access.

## Versions

Tagged per release. See [`CHANGELOG.md`](CHANGELOG.md). The inventory JSON schema may change between major versions; don't pin against it.

## Structure

```
SKILL.md                 Orchestrator that routes all steps and spawns subagents
report-template.md       Output report template
phases/                  Phase subagent prompts
scripts/inventory.py     Deterministic inventory (SQL, concepts, catalogs)
scripts/dispatch_prep.py Review-packet generation, importance scoring
scripts/docs_scan.py     Deterministic docs scan (optional docs mode)
scripts/tests/           Regression gates for the deterministic checks
examples/                Example audit reports
test-fixtures/           Test projects for manual smoke testing
CHANGELOG.md             Version history
TROUBLESHOOTING.md       Common issues and fixes
LICENSE                  MIT
```

## Troubleshooting

See [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) for common failure modes.

## License

MIT. See [LICENSE](LICENSE).

---

*Made by the team behind [Cassis](https://getcassis.com).*
