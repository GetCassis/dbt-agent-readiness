# dbt-agent-readiness

Find the places your AI analyst will return a plausible — but wrong — answer.

`dbt-agent-readiness` is a Claude Code skill that audits a dbt project for
ambiguous metrics, unsafe joins, misleading documentation, invalid columns,
and unclear model grain. It is built for dbt teams piloting AI analysts,
copilots, or internal data agents.

The audit produces one evidence-backed Markdown report containing:

- what an agent will get wrong today
- what still needs runtime verification
- which models are safe to query
- what to fix first

It does not query your warehouse, require warehouse credentials, or modify your
dbt models and configuration.

## Quick start

Clone the skill into your personal Claude Code skills directory:

```bash
git clone https://github.com/GetCassis/dbt-agent-readiness ~/.claude/skills/dbt-agent-readiness
python3 -m pip install -r ~/.claude/skills/dbt-agent-readiness/requirements.txt
```

Then ask Claude Code:

```text
Run the dbt-agent-readiness skill on /path/to/dbt/project
```

The report is written to `{project_path}/dbt-agent-readiness.md`.

### Requirements

- [Claude Code with Skills support](https://code.claude.com/docs/en/skills)
- Python 3.9+
- `pyyaml` and [`sqlglot`](https://github.com/tobymao/sqlglot), installed by
  the command above

Running `dbt compile` in the target project before the audit is recommended.
It lets the skill resolve generated columns from macros such as
`dbt_utils.star`, `SELECT *`, and Jinja loops. When compiled SQL is unavailable,
checks that cannot be supported confidently are suppressed instead of reported
as findings.

## See what it finds

On the bundled 10-model test project, the audit finds four concrete ways an
agent can fail:

| Failure | What the agent gets wrong |
|---|---|
| Inconsistent entity names | Misses rows when joining `customer_id`, `cust_id`, and `user_id` |
| Competing revenue marts | Picks between two plausible models with different grains |
| Misleading descriptions | Treats labels such as “The amount” as sufficient metric semantics |
| Phantom documentation | Selects `customers.loyalty_tier`, which is declared in YAML but not emitted by SQL |

Each finding includes code evidence, affected models, blast radius, a proposed
fix, and an effort estimate. See the
[full sample report](examples/messy-jaffle-shop-audit.md).

## What it checks

| Failure mode | Examples |
|---|---|
| Wrong metric or table | Competing revenue definitions, COUNT/SUM disagreement, undeclared grain |
| Missed or duplicated rows | Inconsistent entity names, unsafe joins, missing uniqueness guarantees |
| Query failure | Broken `ref()`, YAML columns absent from SQL, undefined SQL references |
| Hidden semantics | Undisclosed filters, unit drift, one column name used for different entities |
| Unreliable context | Weak descriptions, stale docs, conflicting definitions, off-repo sources |

The report separates these into two evidence levels:

- **Blockers** are code-evidenced failures an agent can hit today.
- **Hygiene** items are risk factors. Each comes with a query or concrete step
  to verify, promote, or dismiss it.

## How it works

1. **Deterministic inventory.** Python scans dbt SQL, YAML, tests, lineage,
   semantic-layer metadata, and `target/manifest.json` when available.
2. **Targeted review.** Claude reviews flagged concepts and important models,
   rather than rereading every file indiscriminately.
3. **Root-cause report.** Related symptoms are collapsed into a short list of
   blockers, verification work, safe starting models, and prioritized fixes.

Small projects are analyzed inline. Larger projects use the same full-project
inventory plus focused parallel reviews, with checkpoints before expensive
deep-pass work. See [`SKILL.md`](SKILL.md) for the current dispatch behavior.

## What the report contains

1. **Readiness verdict:** ready, not ready, or unsafe, with distance to ready.
2. **Blockers:** failures backed by code evidence, with affected models, blast
   radius, fix, and effort.
3. **Hygiene:** risks paired with runnable verification queries or checks.
4. **Safe starting perimeter:** models an agent can query safely today or after
   one small fix.
5. **Remediation backlog:** fixes prioritized into this week, this sprint, and
   later.

## Optional: include documentation outside dbt

The audit is dbt-only by default. To map context in repository docs, runbooks,
READMEs, or other Markdown files, opt in explicitly:

```text
Run dbt-agent-readiness on /path/to/dbt/project and include the docs
```

If the dbt project sits inside a larger repository, you can name the external
documentation location:

```text
Run dbt-agent-readiness on ./transform/analytics and scan the docs in ./docs
```

Docs mode reports coverage gaps, definitions that disagree, docs that claim
columns a model does not emit, stale material, and links to context an agent
cannot read in Google Docs, Confluence, Notion, or Slack. The deterministic scan
reads the corpus; Claude sees only short snippets associated with flagged
findings, so model usage scales with findings rather than document volume.

## Accuracy and validation

The deterministic layer has 126 regression checks covering SQL column
extraction, multi-hop CTEs, macros, broken column references, fan-out joins,
documentation drift, and false-positive suppression. Test fixtures include
ground-truth files that distinguish planted failures from valid dbt patterns.

The audit is conservative when evidence is incomplete:

- macro-dependent column checks are suppressed when compiled SQL is required
- missing tests remain Hygiene until a verification query shows a real failure
- related findings are clustered into root causes rather than counted as
  independent blockers

See [`CHANGELOG.md`](CHANGELOG.md) for validation notes and precision changes by
release.

## Data handling

The skill reads SQL, YAML, descriptions, and optionally
`target/manifest.json` from your local dbt project. Claude Code sends relevant
content to Anthropic as part of its normal operation. The skill itself opens no
network connections at runtime, executes no warehouse queries, and needs no
warehouse credentials. It writes only `{project_path}/dbt-agent-readiness.md`.

## What this audit cannot detect

- Runtime data quality such as null rates, freshness, and row counts. Hygiene
  findings include queries you can run against the warehouse.
- Source-system changes or upstream format drift.
- Whether a join is conceptually correct for your business domain.
- Query frequency or real usage patterns without query logs.
- Metric conflicts that exist only in BI tools such as Looker or Tableau.

## After the audit

The report says what an agent will get wrong today. Fixing the dbt project closes part of it. The
rest is context that does not live in dbt at all: what a row means, which metric is the defined
one, how two tables join. The [context bootstrap kit](https://github.com/GetCassis/ontology-bootstrap)
assembles that from the sources your stack already has — the dbt project, the warehouse schema,
dashboards, query history and docs — and drafts a reviewable ontology with the evidence attached.

## Repository map

```text
SKILL.md                 Audit workflow and dispatch rules
report-template.md       Output report template
phases/                  Focused review instructions
scripts/inventory.py     Deterministic dbt inventory and checks
scripts/dispatch_prep.py Review packets and importance scoring
scripts/docs_scan.py     Optional deterministic docs scan
scripts/tests/           Regression checks
examples/                Example audit reports
test-fixtures/           dbt projects with planted ground truth
CHANGELOG.md             Release history and validation notes
TROUBLESHOOTING.md       Common failures and fixes
```

## Versions and troubleshooting

Releases are tagged. See [`CHANGELOG.md`](CHANGELOG.md) before depending on the
inventory JSON schema, which may change between major versions.

For setup and audit failures, see [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md).

## License

MIT. See [LICENSE](LICENSE).

---

*Made by the team behind [Cassis](https://getcassis.com).*
