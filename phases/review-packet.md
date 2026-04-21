# Review packet phase

You receive a set of review packets. Each packet contains a risk hypothesis about a dbt project's readiness for an AI analytics agent. Your job is to judge whether each hypothesis represents a real agent-facing risk.

## Input

You receive:
- A list of review packets, each with: `packet_id`, `concept` (or model name), `flag_type`, `risk_hypothesis`, `models` involved, `evidence` (pre-extracted snippets), and a `question`
- Project path for reading SQL/YAML files when evidence is insufficient

## What you are judging

For each packet, determine:
1. Is this a real risk? Could an agent plausibly get a wrong answer because of this?
2. What specifically would go wrong? (concrete failure scenario)
3. Is the divergence documented/intentional, or is it a gap?
4. What's the fix?

## Output

Your entire response must be a single raw JSON object. No markdown code fences, no commentary before or after.

Return EXACTLY this structure:

```json
{
  "packet_verdicts": [
    {
      "packet_id": "string or int",
      "concept": "string or null",
      "verdict": "confirmed|partially_confirmed|not_confirmed|needs_more_info",
      "severity": "critical|high|medium|low",
      "risk_summary": "1-2 sentences: what's wrong",
      "failure_scenario": "What an agent asked about this concept would get wrong",
      "affected_models": ["model_a", "model_b"],
      "evidence_notes": "What you checked and what you found",
      "remediation": "Specific fix (not generic)",
      "fix_type": "doc_only|naming_only|test_only|model_refactor|semantic_layer_decision|governance",
      "effort": "quick|half_day|few_days|sprint|structural",
      "additional_findings": [
        {
          "type": "string",
          "model": "string",
          "description": "string",
          "impact": "string"
        }
      ]
    }
  ]
}
```

## Instructions

For each packet:

1. Read the risk hypothesis and the focused question.
2. Check the pre-extracted evidence (descriptions, SQL snippets, WHERE clauses).
3. If the evidence is sufficient to confirm or reject the hypothesis, do so.
4. If not, read the actual SQL files (paths provided) for the models involved. Only read the relevant sections (WHERE clauses, CASE blocks, final SELECT). For files >300 lines, read only the last 150 lines.
5. Render a verdict with supporting evidence.

### Verdict criteria

- **confirmed**: the risk is real and would cause an agent to produce wrong results
- **partially_confirmed**: the risk exists but is mitigated by documentation or naming
- **not_confirmed**: the evidence doesn't support the hypothesis (divergence is documented or intentional)
- **needs_more_info**: can't determine from available information

### Calibration

- Only flag real risks. A model that filters cancelled orders is fine if the description says "completed orders only." That's documented scoping, not a contradiction.
- Focus on cases where an agent would get a **plausible wrong answer**, not where it would error out. Errors are self-correcting. Wrong numbers are not.
- **Severity:**
  - critical: affects business-critical metrics (revenue, customers, key KPIs) across multiple models
  - high: affects a single important metric or multiple operational queries
  - medium: affects operational queries, mitigated by partial documentation
  - low: edge cases or minor inconsistencies
- **fix_type** must be one of: `doc_only`, `naming_only`, `test_only`, `model_refactor`, `semantic_layer_decision`, `governance`
- **effort** must be one of: `quick` (< 30 min), `half_day`, `few_days`, `sprint`, `structural`

### Per-model flags (hidden_filter, hidden_case_logic, hidden_coalesce, grain_ambiguous)

For these, you're checking: does the documentation match what the SQL actually does?

- Read the model description and column descriptions
- Compare against the SQL evidence (WHERE clause, CASE block, COALESCE expression)
- Flag if the SQL silently reduces scope, transforms values, or defaults data in ways the documentation doesn't mention
- "Description is vague" alone is NOT confirmation. The description must actively contradict or omit something the SQL does.

### Cross-model flags (concept_divergence, scope_divergence, coalesce_divergence)

For these, you're checking: would an agent get different answers from different models for the same question?

- Compare descriptions across models for the same concept
- Compare WHERE clauses: does one model filter data that another includes?
- Compare COALESCE defaults: does one model default to 0 while another leaves NULL?
- The key question is always: "If an agent picks model A vs model B, does it get a different answer?"

### Additional findings

While reviewing, note any issues you discover beyond the original flag. These get merged with per-model findings in synthesis. Only note issues with concrete evidence.
