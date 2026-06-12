# Troubleshooting

Common failures and fixes. If you hit something not listed here, file an issue with the inventory output (or the error).

## "pyyaml is required"

The inventory script needs PyYAML to parse schema files deterministically. Without it, the skill falls back to LLM-based inventory, which is much slower, less accurate, and produces no concept index or review queue.

**Fix:**
```bash
pip install pyyaml
# or: pip3 install pyyaml
# or (macOS): brew install libyaml && pip install pyyaml
```

Re-run the audit.

## "No dbt_project.yml found"

The skill looks for `dbt_project.yml` at the target path. If you pointed it at a subdirectory (e.g., `models/`) or a monorepo root, it can't locate the project config.

**Fix:** Point the skill at the directory containing `dbt_project.yml`:

```
audit /path/to/my_project  ✓
audit /path/to/my_project/models  ✗
```

## Phantom-column findings look wrong

Every phantom-column row in the report is high-confidence: the YAML declares a column that the SQL demonstrably doesn't emit. If you see a row that looks wrong, the most common cause is a macro (`dbt_utils.star`, `SELECT *`, or a Jinja `for`-loop) that the static analyzer couldn't resolve.

**Fix:** run `dbt compile` in the project root, then re-run the audit. The skill will read `target/manifest.json` and resolve the macros.

```bash
cd /path/to/my_project
dbt compile
# then re-run the skill
```

When no manifest is available and macros are involved, the skill suppresses phantom findings on those models (they move to `catalogs.phantom_columns_suppressed_no_manifest`) and emits one "run `dbt compile`" notice instead of per-model noise.

## "Audit is incomplete, only N dimensions returned"

A subagent returned invalid JSON or timed out. The skill proceeds with the data it has rather than retrying.

**Fix:** re-run the audit. If it happens repeatedly:
- Check if the project is unusually large (>500 models), and chunk it by folder.
- Check if the dbt project has unusually long descriptions or macros (subagent token limits may be hitting).
- File an issue with the failing subagent name.

## Huge projects (>500 models)

The skill checkpoints before spawning subagents on projects >100 models and asks for confirmation. For >500 models, consider:

- Running the inventory script alone first (`python3 scripts/inventory.py /path/to/project`) to see the scale.
- Auditing a subset by temporarily restricting `model-paths` in `dbt_project.yml`.
- Pre-compiling with `dbt compile` so manifest-based column resolution is fast.

Estimated wall time:
- 10 to 50 models: 2 to 5 minutes
- 50 to 200 models: 5 to 15 minutes
- 200 to 500 models: 10 to 30 minutes
- \>500 models: 30+ minutes, depends on semantic-layer and exposures complexity

## Partial YAML coverage

If many columns exist in SQL but not in YAML, the inventory flags them as missing descriptions (not phantom columns, which are the reverse: YAML declares what SQL doesn't emit).

This is expected for staging-only layers or "hidden: true" models. If a core/mart model has <50% column coverage, that's a description gap the audit will flag.

## Global severity looks wrong

If your `dbt_project.yml` uses a Jinja expression like `+severity: "{{ env_var('CI_SEVERITY', 'warn') }}"`, the inventory extracts the `'warn'` default argument. If your actual CI runs with `CI_SEVERITY=error`, the audit will note "inferred from env_var default" but won't know about the override.

The severity field is one line in Hygiene, not a Blocker, so a mis-reading isn't load-bearing.

## Report is too long

The Blockers + Safe perimeter + Remediation backlog + Coverage snapshot should fit in ~100 lines. The Hygiene section and appendix can be much longer.

If the top-of-report narrative is dominated by appendix material, you have too many Blockers being emitted. The synthesis rules in `SKILL.md` Step 5b cap at 6 Blockers. If more are arriving, cluster aggressively or re-run.

## Report is unexpectedly positive

The audit is evidence-based: if no code-level issues are detected, it won't manufacture findings. Check:

- Does the project use the semantic layer heavily? Rich semantic-layer metadata reduces surfaced findings.
- Does it have a published glossary? If yes and you didn't pass it, the business-terms subagent couldn't use it.
- Is the project small (<20 models)? The review-packet threshold is 30 models; below that, only inline analysis runs.

Run the inventory script alone to see the raw data:

```bash
python3 scripts/inventory.py /path/to/project | python3 -m json.tool | less
```

## How do I reset between runs?

The skill writes to `{project_path}/dbt-agent-readiness.md` and cleans up temp inventory JSONs. To fully reset:

```bash
rm /path/to/project/dbt-agent-readiness.md
rm -f /tmp/inventory-*.json
```

Then re-run.

## Something else

Open an issue at https://github.com/GetCassis/dbt-agent-readiness/issues with:
1. The prompt you used in Claude Code
2. The size of the project (`find . -name '*.sql' -not -path '*/dbt_packages/*' -not -path '*/target/*' | wc -l`)
3. The error message or the first ~20 lines of the report
4. Skill version (from `CHANGELOG.md` or the latest git tag)
