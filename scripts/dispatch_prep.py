#!/usr/bin/env python3
"""
Dispatcher preparation for the dbt-agent-readiness deep pass.

Consumes the inventory JSON (produced by inventory.py) and emits the
derived structures that SKILL.md Step 2c / 3b / 3c previously computed
inline:

- `review_packets`: review_queue grouped by concept (Step 2c).
- `importance`: per-model importance scores + deep_pass_scope (Step 3b).
- `validation`: structural invariant checks on the inventory (Step 3c).
- `spot_check`: models flagged by `catalogs.yaml_vs_sql_column_count_diff`
  (Step 3d — replaces the manual "read 2 high-importance YAML files"
  step with a deterministic pass).

Usage:  python3 dispatch_prep.py /path/to/inventory.json
Output: JSON to stdout. Exit 0 on success, 1 on error (JSON error on stdout).
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


_SEV_RANK = {'high': 3, 'medium': 2, 'low': 1}


def _sev_rank(sev):
    if isinstance(sev, (int, float)):
        return sev
    return _SEV_RANK.get(str(sev).lower(), 0)


RISK_HYPOTHESES = {
    'scope_divergence': ("These models filter this concept differently — an "
                         "agent would get different answers depending on "
                         "which model it queries"),
    'concept_divergence': ("This concept may be defined inconsistently "
                           "across models"),
    'coalesce_divergence': ("Inconsistent default handling may produce "
                            "subtly different aggregates"),
    'hidden_filter': ("Undocumented filter silently reduces this model's "
                      "scope"),
    'hidden_case_logic': ("Undocumented CASE logic transforms values "
                          "without documentation"),
    'hidden_coalesce': ("Undocumented COALESCE default may affect "
                        "aggregates"),
    'grain_ambiguous': ("No grain declared on this model — agent can't "
                        "know what one row represents"),
    'incremental_asymmetry': ("Incremental strategy may produce different "
                              "results than full refresh"),
}


def build_review_packets(review_queue, models_dict, max_models_per_packet=5,
                         hard_cap=25):
    """Group review_queue flags into packets keyed by concept.

    Per-model flags (concept=None) get individual packets. Concept flags
    get grouped. Each packet lists up to 5 models (highest inbound_refs).
    Returns up to `hard_cap` packets, merging the lowest-severity remainder
    into a single "miscellaneous" packet if needed.
    """
    if not review_queue:
        return []

    # Group by concept (or per-flag for concept=None)
    concept_groups = defaultdict(list)
    for flag in review_queue:
        key = flag.get('concept') or f"__perflag__:{flag.get('flag_type')}:{flag.get('model')}"
        concept_groups[key].append(flag)

    packets = []
    for key, flags in concept_groups.items():
        # Collect all models referenced across flags in this group
        all_models = []
        for f in flags:
            ms = f.get('models') or ([f.get('model')] if f.get('model') else [])
            for m in ms:
                if m and m not in all_models:
                    all_models.append(m)
        # Sort models by inbound_refs desc, cap at max
        all_models.sort(
            key=lambda m: -(models_dict.get(m, {}).get('inbound_refs', 0)))
        models_in_packet = all_models[:max_models_per_packet]

        flag_types = sorted({f.get('flag_type') for f in flags if f.get('flag_type')})
        risk_hypo = ' | '.join(
            RISK_HYPOTHESES.get(ft, 'Review this risk') for ft in flag_types)

        concept = flags[0].get('concept')
        packet = {
            'packet_id': key if concept else f"perflag_{flags[0].get('flag_type')}_{flags[0].get('model')}",
            'concept': concept,
            'flag_types': flag_types,
            'risk_hypothesis': risk_hypo,
            'models': models_in_packet,
            'evidence': _build_evidence(models_in_packet, models_dict),
            'question': _build_question(concept, flag_types),
            '_severity': max(
                (_sev_rank(f.get('severity')) for f in flags), default=0),
        }
        packets.append(packet)

    # Severity sort (desc), then cap
    packets.sort(key=lambda p: -p['_severity'])
    if len(packets) > hard_cap:
        kept = packets[:hard_cap - 1]
        rest = packets[hard_cap - 1:]
        misc_models = sorted({m for p in rest for m in p['models']})[:10]
        kept.append({
            'packet_id': 'miscellaneous',
            'concept': None,
            'flag_types': sorted({ft for p in rest for ft in p['flag_types']}),
            'risk_hypothesis': ('Lower-severity flags collapsed into a single '
                                'miscellaneous packet for review budget.'),
            'models': misc_models,
            'evidence': {},
            'question': ('Scan these flagged models/concepts for any true '
                         'issues worth calling out.'),
            '_severity': 0,
        })
        packets = kept

    for p in packets:
        p.pop('_severity', None)
    return packets


def _build_evidence(models_in_packet, models_dict):
    descriptions = {}
    where_clauses = {}
    case_when_blocks = {}
    coalesce_exprs = {}
    for m in models_in_packet:
        md = models_dict.get(m, {})
        descriptions[m] = (md.get('description_text') or '').strip()[:500]
        snippets = md.get('sql_snippets') or {}
        where_clauses[m] = (snippets.get('where_clauses') or [])[:2]
        case_when_blocks[m] = (snippets.get('case_when_blocks') or [])[:2]
        coalesce_exprs[m] = (snippets.get('coalesce_exprs') or [])[:2]
    return {
        'descriptions': descriptions,
        'where_clauses': where_clauses,
        'case_when_blocks': case_when_blocks,
        'coalesce_exprs': coalesce_exprs,
    }


def _build_question(concept, flag_types):
    if concept:
        return f"Do these models define '{concept}' consistently?"
    if flag_types:
        return f"Does this model have a real issue flagged by {flag_types[0]}?"
    return "Review this flag for a real issue."


def compute_importance(models, exposures):
    """Compute importance scores and deep_pass_scope selection."""
    exposure_refs = set()
    for e in exposures or []:
        for dep in e.get('depends_on') or []:
            # depends_on may be "ref('x')" or "x"
            if isinstance(dep, str):
                if dep.startswith('ref('):
                    inner = dep[len('ref('):].rstrip(')').strip().strip("'").strip('"')
                    exposure_refs.add(inner)
                else:
                    exposure_refs.add(dep)

    scored = []
    for m in models:
        name = m['name']
        score = 0
        reasons = []
        if m.get('inbound_refs', 0) >= 3:
            score += 3
            reasons.append(f"inbound_refs={m['inbound_refs']}")
        if name in exposure_refs:
            score += 2
            reasons.append('exposure')
        if m.get('has_semantic_model'):
            score += 2
            reasons.append('semantic_model')
        if m.get('materialization') in ('table', 'incremental'):
            score += 1
            reasons.append(f"mat={m['materialization']}")
        # leaf node: no outbound refs
        if not (m.get('outbound_refs') or []):
            score += 1
            reasons.append('leaf')
        if m.get('has_pk_test'):
            score += 1
            reasons.append('pk_test')
        scored.append({
            'model': name,
            'importance': score,
            'reasons': reasons,
            'inbound_refs': m.get('inbound_refs', 0),
        })

    scored.sort(key=lambda r: (-r['importance'], -r['inbound_refs'], r['model']))

    # Deep pass scope: importance >= 3, fallback to 2, cap at 50
    scope = [r for r in scored if r['importance'] >= 3]
    if len(scope) < 5:
        scope = [r for r in scored if r['importance'] >= 2]
    if len(scope) > 50:
        scope = scope[:50]

    return {'scores': scored, 'deep_pass_scope': scope}


def validate_inventory(inv):
    """Structural invariant checks from SKILL.md Step 3c."""
    issues = []
    models = inv.get('models') or []
    total = inv.get('total_models', 0)

    # 1. total_models matches models array length
    if total != len(models):
        issues.append({
            'check': 'total_models_matches_array',
            'ok': False,
            'detail': f'total_models={total} but len(models)={len(models)}',
        })
    else:
        issues.append({'check': 'total_models_matches_array', 'ok': True})

    # 5. inbound_refs resolved (no -1)
    unresolved = [m['name'] for m in models if m.get('inbound_refs') == -1]
    issues.append({
        'check': 'inbound_refs_resolved',
        'ok': not unresolved,
        'detail': f'{len(unresolved)} models have inbound_refs=-1' if unresolved else '',
    })

    # 3. orphan columns: column.model exists in models array
    model_names = {m['name'] for m in models}
    orphan_cols = [c for c in (inv.get('columns') or [])
                   if c.get('model') not in model_names]
    issues.append({
        'check': 'no_orphan_columns',
        'ok': not orphan_cols,
        'detail': f'{len(orphan_cols)} orphan column entries' if orphan_cols else '',
    })

    return issues


def build_spot_check(inv):
    """Surface deterministic spot-check results: YAML-vs-SQL column count
    diffs. Replaces the "read 2 high-importance YAML files" manual step.
    """
    catalogs = inv.get('catalogs') or {}
    diffs = catalogs.get('yaml_vs_sql_column_count_diff') or []
    return {
        'method': 'yaml_vs_sql_column_count_diff',
        'n_flagged': len(diffs),
        'top_5': diffs[:5],
    }


def main():
    if len(sys.argv) < 2:
        json.dump({'error': 'usage',
                   'message': 'dispatch_prep.py <inventory.json>'},
                  sys.stdout)
        sys.exit(1)

    inv_path = Path(sys.argv[1])
    if not inv_path.exists():
        json.dump({'error': 'not_found', 'message': str(inv_path)}, sys.stdout)
        sys.exit(1)

    try:
        with open(inv_path) as f:
            inv = json.load(f)
    except Exception as e:
        json.dump({'error': 'parse_failed', 'message': str(e)}, sys.stdout)
        sys.exit(1)

    models = inv.get('models') or []
    models_dict = {m['name']: m for m in models}
    review_queue = inv.get('review_queue') or []
    exposures = inv.get('exposures') or []

    out = {
        'inventory_version': inv.get('inventory_version'),
        'review_packets': build_review_packets(review_queue, models_dict),
        'importance': compute_importance(models, exposures),
        'validation': validate_inventory(inv),
        'spot_check': build_spot_check(inv),
    }
    json.dump(out, sys.stdout, indent=2, default=str)


if __name__ == '__main__':
    main()
