#!/usr/bin/env python3
"""docs_scan.py — optional documentation scanner for dbt-agent-readiness (scanner v1.5).

Deterministic (near-zero-token) scan of documentation that lives OUTSIDE the
dbt layer: repo `docs/`, runbooks, READMEs, or user-pointed `.md/.mdx/.rst/.txt`
sources. Reports where context lives, where it duplicates, where it drifts from
the code, where it goes stale, and where it points off-repo at sources an agent
cannot read.

Design (locked 2026-06-19):
  - dbt-only stays the default; this runs only when the orchestrator opts in.
  - No composite metric. Findings and counts only. Coverage is a plain ratio.
  - Audit, don't infer. Present-state facts only.
  - Deterministic-first: NO doc prose ever enters an LLM here. The light LLM
    pass (phases/docs.md) sees only the short snippets in `llm_queue`.
  - Cost scales with number of findings, not doc volume.

The script reuses inventory.py for the dbt identifier set and the project
config. It accepts an already-built inventory JSON (`--inventory`, the file
Step 2a writes to /tmp) to avoid re-parsing the project; if not given it builds
one in-process.

Severity is NOT decided here. Each `multi_home_candidate` carries the two
deterministic facts synthesis needs plus a derived `severity_if_differ` map:
`is_dbt_identifier`, `authoritative_dbt_definition`, and the conditional severity
a confirmed `differ` would carry under each agent grounding model
(`repo_grounded` / `metadata_grounded`). The LLM supplies only the agree/differ
verdict; synthesis reads `severity_if_differ` to label the finding per archetype.

Usage:
    python3 docs_scan.py --project-path PATH [--inventory inv.json]
                         [--doc-sources GLOB ...] [--max-docs 150]
                         [--max-bytes-per-doc 200000] [--follow-links]
                         [--today YYYY-MM-DD] [--stale-months 18]
                         [--llm-cap 40]

Emits a single JSON object to stdout. Never raises on a single bad doc; a doc
that can't be read is recorded under `doc_corpus.unreadable` and skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import inventory as inv  # noqa: E402  (reuse helpers + build_inventory)

DOCS_SCAN_VERSION = '1.5'  # a doc HOMES an identifier only in a definitional
#                             context (heading subject, column-dictionary row,
#                             "`x` is/means …" prose, or a glossary entry); a
#                             bare mention in prose, SQL, a checklist/metadata
#                             table, or an infra/setup doc no longer counts, so
#                             multi_home is a high-signal set. v1.4 =
#                             multi_home_candidate carries severity_if_differ
#                             (conditional Blocker/Hygiene per agent grounding
#                             model); v1.3 limited column-claim extraction to
#                             column-dictionary tables (generic Property|Value
#                             headers no longer mis-read as a claimed column),
#                             consistent repo-root
#                             path base + byte-identical doc dedup. (v1.2 = tighter
#                             doc classifier, actionable-only gate, manifest-
#                             generated-doc detection, nested-repo auto-discovery)

# Prose doc file types we scan. dbt's own `{% docs %}` blocks also live in .md;
# those are detected by content and excluded from the external corpus.
DOC_EXTS = ('.md', '.mdx', '.rst', '.txt')

# dbt_project.yml path keys that delimit the dbt layer. A prose file under any
# of these is dbt's own, not external context.
DBT_PATH_KEYS = (
    'model-paths', 'source-paths', 'analysis-paths', 'macro-paths',
    'test-paths', 'seed-paths', 'snapshot-paths', 'docs-paths',
)

# Files that are never "external prose" even at the project root.
DBT_LAYER_FILENAMES = frozenset(
    ['dbt_project.yml', 'packages.yml', 'dependencies.yml', 'selectors.yml',
     'profiles.yml'])

# .txt files that are tooling artifacts, not documentation prose. Skipped so the
# "where context lives" count stays honest.
NON_DOC_FILE_RE = re.compile(
    r'^(requirements[\w.-]*\.txt|constraints[\w.-]*\.txt|.*\.lock|.*-lock\.\w+'
    r'|robots\.txt|\.?gitignore)$', re.I)

# ── External-pointer classification ──────────────────────────────────────────
# Off-repo authority an agent cannot read. Order matters: first match wins.
EXTERNAL_HOST_RULES = [
    ('google_docs',   re.compile(r'docs\.google\.com', re.I)),
    ('google_drive',  re.compile(r'drive\.google\.com', re.I)),
    ('google_sheets', re.compile(r'sheets\.google\.com', re.I)),
    ('confluence',    re.compile(r'[\w.-]+\.atlassian\.net/wiki|confluence', re.I)),
    ('jira',          re.compile(r'[\w.-]+\.atlassian\.net/(?:browse|jira)', re.I)),
    ('notion',        re.compile(r'notion\.so|notion\.site', re.I)),
    ('slack',         re.compile(r'[\w.-]+\.slack\.com|slack\.com/archives', re.I)),
    ('airtable',      re.compile(r'airtable\.com', re.I)),
    ('mermaid',       re.compile(r'mermaid\.ink', re.I)),
    ('figma',         re.compile(r'figma\.com', re.I)),
    ('loom',          re.compile(r'loom\.com', re.I)),
    ('github',        re.compile(r'github\.com|githubusercontent\.com', re.I)),
    ('gitlab',        re.compile(r'gitlab\.com', re.I)),
]

# Any absolute http(s) link.
HTTP_LINK_RE = re.compile(r'https?://[^\s)\]>"\'`]+', re.I)

# "this is the single source of truth" / "handbook is authoritative" style
# phrases — a doc deferring authority off to somewhere else.
SSOT_PHRASE_RE = re.compile(
    r'\b(single source of truth|source of truth|authoritative source|'
    r'canonical (?:source|reference)|handbook is|see the handbook|'
    r'refer to (?:the )?(?:handbook|wiki|confluence|notion))\b', re.I)

# ── Staleness ────────────────────────────────────────────────────────────────
STALE_KEYWORDS = [
    'deprecated', 'maintenance mode', 'no longer maintained',
    'not maintained', 'archived', 'do not use', 'superseded',
    'out of date', 'outdated', 'legacy', 'wip', 'draft',
    'todo', 'fixme', 'tbd',
]
STALE_KEYWORD_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in STALE_KEYWORDS) + r')\b', re.I)

# "as of 2021", "last updated 2021-03", "updated: 2022", bare ISO dates.
ISO_DATE_RE = re.compile(r'\b(20\d{2})-(\d{2})-(\d{2})\b')
AS_OF_RE = re.compile(
    r'\b(?:as of|last updated|updated|revised|version dated|effective)'
    r'\s*:?\s*(?:\w+\s+)?(20\d{2})\b', re.I)

# Markdown headings and tables.
H1_RE = re.compile(r'^\#\s+(.+?)\s*$', re.M)
HEADING_RE = re.compile(r'^(\#{1,6})\s+(.+?)\s*$', re.M)
FENCE_RE = re.compile(r'```[\w]*\n(.*?)```', re.DOTALL)

# snake_case / column-like tokens (>=2 chars, must contain a lowercase letter).
IDENT_TOKEN_RE = re.compile(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b')

# Generic identifiers too common to count as a meaningful doc-to-model mention.
COVERAGE_STOPWORDS = frozenset([
    'id', 'name', 'date', 'value', 'type', 'status', 'code', 'key', 'count',
    'amount', 'total', 'data', 'model', 'table', 'column', 'source', 'test',
    'user', 'time', 'day', 'month', 'year', 'flag', 'note', 'label', 'index',
    'true', 'false', 'null', 'all', 'the', 'and', 'for', 'with',
])

# ── Definitional-home signals ────────────────────────────────────────────────
# A doc *homes* an identifier only when it DEFINES it, not when it merely uses
# the word. Four definitional contexts (see `_definitional_homes`): the term is
# a heading's subject, a column-dictionary row key, the subject of a "`x`
# is/means …" prose definition, or a glossary/data-dictionary entry. A bare
# occurrence in prose, SQL, a checklist/metadata table cell, or an infra/setup
# doc is NOT a home — that is the difference between "the doc documents this
# field" and "the doc happens to use the word."

# Glossary entry: a bulleted term followed by ":" / em-dash and its definition
# ("- **fct_revenue**: gross revenue …"). Counted only in glossary-typed docs;
# the same shape in a README ("- `email`: the user's email") is code
# terminology, a homonym source, not a data home.
GLOSSARY_ENTRY_RE = re.compile(
    r'^\s*[-*+]\s+(?:\*\*|__|`)?\s*([a-z][a-z0-9_]+)\s*(?:\*\*|__|`)?\s*[:—]',
    re.M | re.I)

# Term-first prose definition: a backticked identifier directly followed by a
# *definitional* verb ("`fct_revenue` means net revenue", "`x` is defined as …").
# Bare "is"/"are" are excluded on purpose — "`subscription_id` is not null" in a
# changelog is a predicate, not a definition; only verbs that introduce a meaning
# count. The backtick + verb adjacency separates a real definition from a bare
# mention ("a `stage` has to be created") or a colon list ("- `email`: …").
PROSE_DEFN_RE = re.compile(
    r'`([a-z][a-z0-9_]+)`\s+(?:is\s+defined\s+as|defined\s+as|means?\b|'
    r'represents?\b|refers?\s+to\b|denotes?\b|stands?\s+for\b)',
    re.I)

# Words that may sit beside an identifier in a heading without disqualifying it
# as the heading's subject — "## The dim_customers table" is still about
# dim_customers. Any other significant word means the heading is about something
# else ("## Email configuration settings"), so it homes nothing.
_HEADING_DESCRIPTORS = frozenset([
    'the', 'a', 'an', 'and', 'or', 'vs', 'versus', 'model', 'models', 'table',
    'tables', 'column', 'columns', 'field', 'fields', 'source', 'sources',
    'overview', 'details', 'detail', 'definition', 'definitions', 'schema',
    'spec', 'reference',
])

SNIPPET_LEN = 240

# Files that are never a data dictionary regardless of prose content. License
# texts ("1. Definitions"), contributor guides, and AI-agent operating manuals
# were previously misread as glossary/architecture and inflated the gate signal.
_NON_DICTIONARY_FILENAMES = frozenset([
    'notice.md', 'notice', 'contributing.md', 'contributing',
    'code_of_conduct.md', 'security.md', 'authors.md', 'maintainers.md',
    'agent.md', 'agents.md', 'claude.md', 'cursor.md', 'copilot.md',
    'codeowners', 'support.md', 'funding.md',
])
# Path segments whose docs are posts/announcements, not data dictionaries.
_NON_DICTIONARY_PATH_SEGS = frozenset(
    ['blog', 'blogs', 'news', 'posts', 'post', 'releases', 'release'])

# Docs that render their tables from the dbt manifest / a generator at build
# time (Docusaurus components, dbt-docs JSON, "do not edit, generated" headers).
# Their columns come from the dbt layer itself, so they cannot drift and carry
# no hand-authored column claims. Detecting them turns a silent column_drift=0
# into an explicit "docs are generated from dbt, drift-proof" finding.
GENERATED_DOC_RE = re.compile(
    r'<\s*JsonDataTable|jsonPath\s*=|nodes\.[\w.\\]+\.columns|'
    r'do not edit[^\n]{0,40}generated|generated by dbt|auto-?generated',
    re.IGNORECASE)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _today(arg: str | None) -> date:
    if arg:
        return datetime.strptime(arg, '%Y-%m-%d').date()
    return date.today()


def _word_re(token: str) -> re.Pattern:
    """Whole-token, case-insensitive match for an identifier."""
    return re.compile(r'(?<![\w.])' + re.escape(token) + r'(?![\w])', re.I)


def _snippet(text: str, idx: int, length: int = SNIPPET_LEN) -> str:
    start = max(0, idx - length // 3)
    end = min(len(text), idx + (2 * length) // 3)
    s = text[start:end].replace('\n', ' ').strip()
    return re.sub(r'\s+', ' ', s)


def _classify_doc_type(relpath: str, head: str) -> str:
    """Deterministic best-effort doc classification. The LLM refines this.

    Tightened (v1.2): license / contributor / agent-guide files and blog/news
    posts are never read as glossary or architecture just because their prose
    contains a generic word like "definitions" or "data model". Head matches
    are restricted to the title region (first ~200 chars) rather than 600 chars
    of body prose, and the glossary/architecture needles are made specific.
    """
    rp = relpath.lower().replace('\\', '/')
    fn = rp.rsplit('/', 1)[-1]
    segs = rp.split('/')[:-1]  # directory segments, excluding the filename
    if fn in ('readme.md', 'readme.rst', 'readme.txt', 'readme.mdx'):
        return 'readme'
    if fn.startswith(('license', 'licence')) or fn in _NON_DICTIONARY_FILENAMES:
        return 'other'
    if any(seg in _NON_DICTIONARY_PATH_SEGS for seg in segs):
        return 'other'
    head_top = head[:200].lower()  # title region only, not 600 chars of prose
    pairs = [
        ('glossary', ('glossary', 'data dictionary', 'data-dictionary',
                      'metric definitions', 'field definitions',
                      'terminology')),
        ('runbook',  ('runbook', 'playbook', 'on-call', 'oncall', 'incident',
                      'troubleshoot')),
        ('architecture', ('architecture', 'data model', 'entity relationship',
                          'schema design', 'lineage diagram',
                          'pipeline overview')),
        ('onboarding', ('onboarding', 'getting started', 'setup guide',
                        'quickstart', 'quick start')),
        ('process', ('process', 'workflow', 'guideline', 'convention', 'policy',
                     'standard operating')),
        ('changelog', ('changelog', 'release notes')),
    ]
    for label, needles in pairs:
        if any(n in fn for n in needles) or any(n in head_top for n in needles):
            return label
    return 'other'


def _extract_links(text: str):
    """Return (by_category dict, total, ssot_phrase_present)."""
    by_cat: dict[str, int] = {}
    total = 0
    for m in HTTP_LINK_RE.finditer(text):
        url = m.group(0)
        total += 1
        cat = 'other_external'
        for label, rx in EXTERNAL_HOST_RULES:
            if rx.search(url):
                cat = label
                break
        by_cat[cat] = by_cat.get(cat, 0) + 1
    return by_cat, total, bool(SSOT_PHRASE_RE.search(text))


def _extract_staleness(text: str, today: date, stale_months: int):
    """Return dict or None. Flags keyword markers and old explicit dates."""
    markers = sorted({m.group(1).lower() for m in STALE_KEYWORD_RE.finditer(text)})
    dates = []
    for m in ISO_DATE_RE.finditer(text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(date(y, mo, d))
        except ValueError:
            continue
    for m in AS_OF_RE.finditer(text):
        try:
            dates.append(date(int(m.group(1)), 1, 1))
        except ValueError:
            continue
    oldest = min(dates) if dates else None
    stale_cutoff_months = (today.year - oldest.year) * 12 + (today.month - oldest.month) \
        if oldest else 0
    date_is_stale = bool(oldest) and stale_cutoff_months >= stale_months
    if not markers and not date_is_stale:
        return None
    return {
        'markers': markers,
        'oldest_date': oldest.isoformat() if oldest else None,
        'months_since_oldest_date': stale_cutoff_months if oldest else None,
        'stale_by_date': date_is_stale,
        'stale_by_marker': bool(markers),
    }


# Header cells that mark a markdown table as a *column dictionary* (vs a generic
# key/value metadata table like `| Property | Value |`, `| Setting | Value |`).
# Only column dictionaries have their data-row first cells mined as claimed
# columns; the header row itself is never treated as a column. This stops generic
# table headers (Property, Setting, Metric, Parameter, Key) leaking in as phantom
# column claims that then read as doc-vs-code drift.
_COL_TABLE_NAME_CELLS = frozenset(
    {'column', 'columns', 'col', 'cols', 'field', 'fields'})
_COL_TABLE_TYPE_CELLS = frozenset(
    {'type', 'types', 'dtype', 'datatype', 'data type', 'data_type',
     'description', 'desc', 'definition', 'comment', 'comments'})


def _md_cells(line: str) -> list:
    return [c.strip().strip('`').strip() for c in line.strip().strip('|').split('|')]


def _is_md_sep_row(cells: list) -> bool:
    return bool(cells) and all(c and set(c) <= {'-', ':'} for c in cells)


def _is_column_table_header(cells: list) -> bool:
    low = {c.lower() for c in cells}
    return bool(low & _COL_TABLE_NAME_CELLS) or bool(low & _COL_TABLE_TYPE_CELLS)


def _extract_column_table_claims(section: str) -> list:
    """Claimed columns from a doc section: data-row first cells of markdown tables
    that are column dictionaries, plus snake_case tokens in fenced code blocks.
    Generic key/value tables (Property|Value, Setting|Value) are skipped, and a
    table header row is never itself emitted as a column."""
    cols: list = []
    lines = section.split('\n')
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if '|' in line and i + 1 < n:
            header = _md_cells(line)
            sep = _md_cells(lines[i + 1])
            if len(header) >= 2 and len(sep) == len(header) and _is_md_sep_row(sep):
                is_col_table = _is_column_table_header(header)
                j = i + 2
                while j < n and '|' in lines[j] and lines[j].strip().startswith('|'):
                    if is_col_table:
                        cells = _md_cells(lines[j])
                        first = cells[0].lower() if cells else ''
                        if first and first not in ('column', 'field', 'name', 'col') \
                                and not (set(first) <= {'-', ':', ' '}):
                            tok = (IDENT_TOKEN_RE.match(first)
                                   or re.match(r'^([a-z][a-z0-9_]*)$', first))
                            if tok:
                                cols.append(tok.group(1))
                    j += 1
                i = j
                continue
        i += 1
    # Fenced blocks: snake_case tokens (distinctive enough to be real identifiers).
    for fence in FENCE_RE.finditer(section):
        for tok in IDENT_TOKEN_RE.finditer(fence.group(1)):
            cols.append(tok.group(1))
    return sorted(set(cols))


def _extract_doc_column_claims(text: str, model_names: set[str]):
    """Best-effort: when a heading names a model, capture column-like tokens from
    that section's column-dictionary tables and fenced blocks.

    Returns a list of {model, claimed_columns, snippet}.
    """
    claims = []
    headings = list(HEADING_RE.finditer(text))
    for i, h in enumerate(headings):
        title = h.group(2).strip()
        # A heading "matches" a model if a model name appears as a whole token.
        matched = None
        for name in model_names:
            if len(name) >= 4 and _word_re(name).search(title):
                matched = name
                break
        if not matched:
            continue
        section_start = h.end()
        section_end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section = text[section_start:section_end]
        cols = _extract_column_table_claims(section)
        if cols:
            claims.append({
                'model': matched,
                'claimed_columns': cols,
                'snippet': _snippet(section, 0, 200),
            })
    return claims


def _heading_subject(title: str) -> str | None:
    """The single identifier a heading is *about* (lowercased), or None. A
    heading homes an identifier only when the identifier IS its subject —
    "## fct_orders", "## The dim_customers table" — not when it merely appears
    inside a longer descriptive title ("## Email configuration settings")."""
    words = re.findall(r'[a-z][a-z0-9_]*', title.lower())
    significant = {w for w in words if w not in _HEADING_DESCRIPTORS}
    if len(significant) != 1:
        return None
    tok = next(iter(significant))
    return tok if len(tok) >= 4 else None


def _column_dict_row_keys(text: str) -> set:
    """First-cell keys of markdown column-dictionary tables (`| customer_id | …`).
    Mirrors `_extract_column_table_claims`' table handling but excludes fenced
    code and generic key/value tables (`| Property | Value |`); used only for
    home detection. A row key is a defining context: the table is the column's
    data dictionary, keyed to it."""
    keys: set = set()
    lines = text.split('\n')
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if '|' in line and i + 1 < n:
            header = _md_cells(line)
            sep = _md_cells(lines[i + 1])
            if (len(header) >= 2 and len(sep) == len(header)
                    and _is_md_sep_row(sep) and _is_column_table_header(header)):
                j = i + 2
                while j < n and '|' in lines[j] and lines[j].strip().startswith('|'):
                    cells = _md_cells(lines[j])
                    first = cells[0].lower() if cells else ''
                    if (first and first not in ('column', 'field', 'name', 'col')
                            and re.fullmatch(r'[a-z][a-z0-9_]+', first)):
                        keys.add(first)
                    j += 1
                i = j
                continue
        i += 1
    return keys


def _definitional_homes(text: str, doc_type: str) -> set:
    """Tokens (lowercased) the doc actually *defines*, vs merely mentions.

    A doc homes an identifier only in a definitional context:
      1. the identifier is a heading's subject ("## fct_orders");
      2. it is the row key of a column-dictionary table;
      3. it is the term of a "`x` is/means/represents …" prose definition;
      4. it is a glossary/data-dictionary entry ("- **x**: …"), counted only in
         a doc whose job is defining terms — a bullet "- `email`: …" inside a
         README/runbook is code terminology, not a data home.

    Fenced code is stripped first, so a query selecting a column or a setup
    snippet exporting a variable is a *use*, never a home. A bare mention in
    prose, a backtick, a checklist/metadata table cell, or SQL does NOT home the
    identifier. This is what shrinks multi_home from a noisy bare-occurrence
    population to the docs that genuinely compete with dbt for a definition."""
    prose = FENCE_RE.sub('\n', text)
    homes: set = set()
    for h in HEADING_RE.finditer(prose):
        tok = _heading_subject(h.group(2))
        if tok:
            homes.add(tok)
    homes |= _column_dict_row_keys(prose)
    for m in PROSE_DEFN_RE.finditer(prose):
        homes.add(m.group(1).lower())
    if doc_type == 'glossary':
        for m in GLOSSARY_ENTRY_RE.finditer(prose):
            homes.add(m.group(1).lower())
    return homes


# ── Boundary: what counts as "the dbt layer" ─────────────────────────────────

def _dbt_layer_dirs(project_path: Path, cfg_raw: dict) -> list[Path]:
    dirs: list[Path] = []
    for key in DBT_PATH_KEYS:
        vals = cfg_raw.get(key)
        if isinstance(vals, str):
            vals = [vals]
        for v in (vals or []):
            dirs.append((project_path / v).resolve())
    # dbt defaults when unspecified.
    for default in ('models', 'analyses', 'macros', 'tests', 'seeds',
                    'snapshots'):
        dirs.append((project_path / default).resolve())
    return dirs


def _is_dbt_doc_block_file(text: str) -> bool:
    return bool(inv.DOC_BLOCK_RE.search(text))


def _in_dbt_layer(path: Path, layer_dirs: list[Path]) -> bool:
    rp = path.resolve()
    if rp.name in DBT_LAYER_FILENAMES:
        return True
    for d in layer_dirs:
        try:
            rp.relative_to(d)
            return True
        except ValueError:
            continue
    return False


# ── Inventory-derived identifier facts ───────────────────────────────────────

def _build_identifier_facts(inventory: dict):
    """Returns (coverage_units, scan_units, identifier_lookup, models, cols_by_model).

    coverage_units: distinctive model & source tables (the unit for
      identifier_coverage — the "docs for these, not those" ratio).
    scan_units: the broader distinctive set matched across docs for mentions and
      multi-home detection — models, source tables, metrics, measures, and
      *described* columns (an undescribed column can't create a dbt-vs-doc
      contradiction, and scanning every column would be noise).
    identifier_lookup: token -> kind + authoritative-definition facts, used to
      annotate multi-home candidates for the reliability rule.
    """
    models = {m['name']: m for m in inventory.get('models', [])}
    columns = inventory.get('columns', [])
    cols_by_model: dict[str, list] = {}
    for c in columns:
        cols_by_model.setdefault(c['model'], []).append(c)

    sem = inventory.get('semantic_layer', {}) or {}
    # inventory.py records the boolean under `has_description` (the rich text is
    # not carried into the inventory dict). Read that, not a `description` key
    # that never exists — otherwise every described MetricFlow metric/measure
    # looks undefined and its prose contradictions over-escalate to Blockers.
    metric_defs = {}
    for mt in (sem.get('metrics') or []):
        if mt.get('name'):
            metric_defs[mt['name']] = bool(mt.get('has_description'))
    measure_defs = {}
    for smodel in (sem.get('semantic_models') or []):
        for ms in (smodel.get('measures') or []):
            if ms.get('name'):
                measure_defs[ms['name']] = bool(ms.get('has_description'))

    lookup: dict[str, dict] = {}
    coverage_units = []
    scan_units = []
    scan_seen = set()

    def add_scan(token, kind):
        key = token.lower()
        if len(token) < 4 or key in COVERAGE_STOPWORDS or key in scan_seen:
            return
        scan_seen.add(key)
        scan_units.append({'token': token, 'kind': kind})

    def good_desc(quality):
        return quality == 'good'

    for name, m in models.items():
        quality = m.get('description_quality')
        fact = {
            'kind': 'model',
            'authoritative_dbt_definition': {
                'exists': bool(m.get('has_description')) and good_desc(quality),
                'source': 'model_description' if m.get('has_description') else None,
                'quality': quality,
            },
        }
        lookup[name.lower()] = {'token': name, **fact}
        if len(name) >= 4 and name.lower() not in COVERAGE_STOPWORDS:
            coverage_units.append({'token': name, 'kind': 'model'})
        add_scan(name, 'model')

    for s in inventory.get('sources', []):
        tbl = s.get('table_name', '')
        if not tbl:
            continue
        qualified = f"{s.get('source_name', '')}.{tbl}"
        fact = {
            'kind': 'source_table',
            'authoritative_dbt_definition': {
                'exists': bool(s.get('has_description')),
                'source': 'source_description' if s.get('has_description') else None,
                'quality': 'good' if s.get('has_description') else None,
            },
        }
        lookup.setdefault(tbl.lower(), {'token': tbl, **fact})
        if len(tbl) >= 4 and tbl.lower() not in COVERAGE_STOPWORDS:
            coverage_units.append({'token': tbl, 'kind': 'source_table',
                                   'qualified': qualified})
        add_scan(tbl, 'source_table')

    # Metrics & measures: authoritative if described in the semantic layer.
    for nm, described in metric_defs.items():
        lookup.setdefault(nm.lower(), {
            'token': nm, 'kind': 'metric',
            'authoritative_dbt_definition': {
                'exists': described, 'source': 'semantic_metric' if described else None,
                'quality': 'good' if described else None}})
        add_scan(nm, 'metric')
    for nm, described in measure_defs.items():
        lookup.setdefault(nm.lower(), {
            'token': nm, 'kind': 'measure',
            'authoritative_dbt_definition': {
                'exists': described, 'source': 'semantic_measure' if described else None,
                'quality': 'good' if described else None}})
        add_scan(nm, 'measure')

    # Column-level: a queryable identifier whose authority is the column desc.
    # Only *described* columns are scanned across docs (an undescribed column
    # has no dbt definition to contradict).
    for model_name, cols in cols_by_model.items():
        for c in cols:
            cn = c['column']
            if len(cn) < 4 or cn.lower() in COVERAGE_STOPWORDS:
                continue
            described = bool(c.get('has_description'))
            entry = lookup.get(cn.lower())
            if entry is None:
                lookup[cn.lower()] = {
                    'token': cn, 'kind': 'column',
                    'authoritative_dbt_definition': {
                        'exists': described, 'source':
                            'column_description' if described else None,
                        'quality': 'good' if described else None}}
            elif described and not entry['authoritative_dbt_definition']['exists']:
                # A model/source already owns this token; if any column with
                # this name is described, mark a definition available.
                entry['authoritative_dbt_definition'] = {
                    'exists': True, 'source': 'column_description',
                    'quality': 'good'}
            if described:
                add_scan(cn, 'column')
    return coverage_units, scan_units, lookup, models, cols_by_model


# ── Main scan ────────────────────────────────────────────────────────────────

# Conventional names for the subdir a dbt project lives in inside a larger data
# repo. When the dbt project sits under one of these (or exactly one level below
# the repo root), the repo's top-level docs are authoritative context above the
# dbt layer and worth auto-including. A dbt project buried elsewhere (e.g. under
# `test-fixtures/` or `examples/` in a tooling repo) is NOT auto-expanded.
_DATA_SUBDIR_NAMES = frozenset([
    'transform', 'warehouse', 'dbt', 'dbt_project', 'analytics', 'analytics-dbt',
    'snowflake-dbt', 'bigquery-dbt', 'models', 'projects', 'dwh', 'elt',
    'data-warehouse', 'datawarehouse', 'data', 'pipelines',
])


def _find_repo_root(project_path: Path):
    """Walk up from the dbt project looking for a VCS root. Returns the repo
    root Path, or None if none is found at or above the project."""
    p = project_path.resolve()
    for cand in [p, *p.parents]:
        if (cand / '.git').exists() or (cand / '.hg').exists():
            return cand
    return None


def _should_expand_to_repo_root(project_path: Path, repo_root: Path) -> bool:
    """Fix G guard: auto-expand discovery to the repo root only when the dbt
    project plausibly *is* the repo's data project — i.e. it sits under a
    conventional data-layer subdir, or exactly one level below the root. This
    grabs repo-level docs above a real nested project (warehouse/, transform/)
    without escaping into an unrelated enclosing repo."""
    try:
        rel_parts = project_path.resolve().relative_to(repo_root).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    return rel_parts[0] in _DATA_SUBDIR_NAMES or len(rel_parts) == 1


def _discover_docs(base: Path, doc_sources, layer_dirs):
    """Return (local_paths, external_source_urls). Deterministic ordering.

    `base` is the discovery root: the dbt project path normally, or the repo
    root when the dbt project is nested (fix G) so repo-level docs above the
    dbt layer are not missed. The dbt layer is excluded downstream regardless.
    """
    external_urls = []
    if doc_sources:
        paths: list[Path] = []
        for src in doc_sources:
            if re.match(r'^https?://', src, re.I):
                external_urls.append(src)
                continue
            p = Path(src)
            if not p.is_absolute():
                # Resolve against the base first (so "docs" means {base}/docs),
                # then fall back to the current directory so a repo root above
                # the project ("../.." or a cwd-relative path) also works.
                cand = base / src
                p = cand if cand.exists() else p
            if p.is_dir():
                for ext in DOC_EXTS:
                    paths.extend(inv.find_files(p, f'*{ext}'))
            elif p.exists():
                paths.append(p)
            else:
                # treat as a glob, base-relative then cwd-relative
                paths.extend(sorted(base.glob(src))
                             or sorted(Path('.').glob(src)))
        candidates = paths
    else:
        candidates = []
        for ext in DOC_EXTS:
            candidates.extend(inv.find_files(base, f'*{ext}'))
    # Dedup + stable sort, dropping tooling artifacts.
    seen = set()
    uniq = []
    for p in sorted(candidates, key=lambda x: str(x)):
        rp = str(p.resolve())
        if rp in seen or NON_DOC_FILE_RE.match(p.name):
            continue
        seen.add(rp)
        uniq.append(p)
    return uniq, external_urls


def scan(project_path: Path, inventory: dict, *, doc_sources=None,
         max_docs=150, max_bytes_per_doc=200_000, follow_links=False,
         today: date, stale_months=18, llm_cap=40) -> dict:
    cfg = inv.parse_project_config(project_path) or {'project_name': 'unknown',
                                                     'raw': {}}
    layer_dirs = _dbt_layer_dirs(project_path, cfg.get('raw', {}))
    coverage_units, scan_units, ident_lookup, models, cols_by_model = \
        _build_identifier_facts(inventory)
    model_names = set(models.keys())

    # Discovery root (fix G): when the dbt project is nested below the repo
    # root and the caller did not pin --doc-sources, discover from the repo
    # root so the authoritative docs that live ABOVE the dbt layer (repo
    # `docs/`, runbooks, top-level READMEs) are not silently missed. The dbt
    # layer itself is still excluded by `_in_dbt_layer`, so the project's own
    # schema docs are never double counted.
    discovery_root = project_path
    nested_dbt_project = False
    if not doc_sources:
        repo_root = _find_repo_root(project_path)
        if (repo_root and repo_root != project_path.resolve()
                and _should_expand_to_repo_root(project_path, repo_root)):
            discovery_root = repo_root
            nested_dbt_project = True

    candidates, external_source_urls = _discover_docs(
        discovery_root, doc_sources, layer_dirs)

    # Filter out dbt-layer files (by location or by doc-block content).
    discovered = []
    dbt_layer_excluded = 0
    unreadable = []
    for p in candidates:
        try:
            raw = p.read_text(encoding='utf-8')
        except Exception as e:
            unreadable.append({'path': str(p), 'error': type(e).__name__})
            continue
        if _in_dbt_layer(p, layer_dirs) or _is_dbt_doc_block_file(raw):
            dbt_layer_excluded += 1
            continue
        discovered.append((p, raw))

    total_discovered = len(discovered)
    dropped = []
    if len(discovered) > max_docs:
        dropped = [str(p) for p, _ in discovered[max_docs:]]
        discovered = discovered[:max_docs]

    # Cite every doc under one consistent base: the smallest directory that
    # contains both the project/discovery anchor AND every scanned doc. Anchoring
    # on discovery_root keeps citations project-rooted (so `docs/x.md` keeps its
    # `docs/` prefix) and climbs to the repo root only when docs live above the
    # project (so `dbt_project/README.md` is not cited as a bare `README.md`). It
    # never over-walks into an unrelated enclosing repo. Mixing bases previously
    # produced ambiguous citations.
    base_inputs = [str(discovery_root.resolve())] + \
        [str(p.resolve().parent) for p, _ in discovered]
    try:
        path_base = Path(os.path.commonpath(base_inputs))
    except ValueError:
        path_base = discovery_root.resolve()

    # Per-doc deterministic extraction.
    docs = []
    # term -> list of (doc_path, snippet) for multi-home across docs.
    term_doc_hits: dict[str, list] = {}
    scan_res = {u['token']: _word_re(u['token']) for u in scan_units}

    ext_by_cat_total: dict[str, int] = {}
    ext_total = 0
    ssot_docs = []
    staleness_flags = []
    all_column_claims = []
    generated_docs = []
    seen_content: dict = {}      # content hash -> first doc path (dedup identical docs)
    duplicate_content = []

    for p, raw in discovered:
        text = raw[:max_bytes_per_doc]
        rel = _relpath(p, path_base)
        # Dedup byte-identical docs (e.g. a doc copied to two locations) so its
        # identifiers, column claims, drift, and pointers are not double counted.
        chash = hashlib.md5(text.encode('utf-8', 'replace')).hexdigest()
        if chash in seen_content:
            duplicate_content.append({'path': rel, 'duplicate_of': seen_content[chash]})
            continue
        seen_content[chash] = rel
        h1 = H1_RE.search(text)
        title = h1.group(1).strip() if h1 else p.stem
        head = text[:600]
        doc_type = _classify_doc_type(rel, head)
        # Fix D: docs whose tables are generated from the dbt manifest cannot
        # drift and carry no hand-authored column claims — record and skip claim
        # extraction so the manifest component reference is not parsed as columns.
        generated = bool(GENERATED_DOC_RE.search(text))
        if generated:
            generated_docs.append(rel)

        by_cat, n_links, ssot = _extract_links(text)
        for k, v in by_cat.items():
            ext_by_cat_total[k] = ext_by_cat_total.get(k, 0) + v
        ext_total += n_links
        if ssot:
            ssot_docs.append(rel)

        stale = _extract_staleness(text, today, stale_months)
        if stale:
            staleness_flags.append({'path': rel, **stale})

        # Identifier mentions, split into bare mentions (the coverage map) and
        # definitional homes (the multi-home signal the LLM eventually sees).
        # Coverage counts any mention; only a definitional home creates a
        # doc-vs-dbt contradiction, so multi_home filters on `home`.
        doc_homes = _definitional_homes(text, doc_type)
        mentions = []
        for tok, rx in scan_res.items():
            m = rx.search(text)
            if m:
                mentions.append(tok)
                tl = tok.lower()
                term_doc_hits.setdefault(tl, []).append({
                    'doc_path': rel, 'snippet': _snippet(text, m.start()),
                    'home': tl in doc_homes})
        mentions.sort()

        claims = [] if generated else _extract_doc_column_claims(text, model_names)
        for c in claims:
            c['doc_path'] = rel
        all_column_claims.extend(claims)

        docs.append({
            'path': rel,
            'size_bytes': len(raw),
            'title': title,
            'doc_type': doc_type,
            'generated_from_manifest': generated,
            'external_pointers': {'by_category': by_cat, 'total': n_links,
                                  'defers_authority_offsite': ssot},
            'staleness': stale,
            'identifier_mentions': mentions,
            'doc_column_claims': [
                {'model': c['model'], 'claimed_columns': c['claimed_columns']}
                for c in claims],
        })

    # ── Aggregate: identifier coverage (plain ratio, model + source table) ───
    documented, undocumented = [], []
    for u in coverage_units:
        tok = u['token']
        if term_doc_hits.get(tok.lower()):
            documented.append(u)
        else:
            undocumented.append(u)
    identifier_coverage = {
        'unit': 'model_and_source_table',
        'total': len(coverage_units),
        'documented': len(documented),
        'undocumented': len(undocumented),
        'documented_list': [u['token'] for u in documented],
        'undocumented_list': [u['token'] for u in undocumented],
    }

    # ── Aggregate: multi-home candidates ────────────────────────────────────
    # A term has more than one home when it appears in >=2 docs, OR in >=1 doc
    # AND has a dbt description. Each candidate carries the deterministic facts
    # synthesis needs for the reliability rule.
    multi_home = []
    for tok_l, doc_hits in term_doc_hits.items():
        # Only count docs that actually *home* the identifier (definitional
        # context), not bare prose mentions. A term mentioned but never defined
        # in any doc cannot create a doc-vs-dbt contradiction.
        home_hits = [d for d in doc_hits if d.get('home')]
        if not home_hits:
            continue
        fact = ident_lookup.get(tok_l)
        n_docs = len({d['doc_path'] for d in home_hits})
        dbt_def = (fact or {}).get('authoritative_dbt_definition',
                                   {'exists': False, 'source': None,
                                    'quality': None})
        # dbt description snippet, when the term is a model/column we documented.
        dbt_snippet = None
        if fact and fact.get('kind') == 'model':
            md = models.get(fact['token'])
            if md and md.get('description_text'):
                dbt_snippet = md['description_text']
        has_dbt_home = bool(dbt_snippet) or dbt_def['exists']
        if n_docs < 2 and not has_dbt_home:
            continue
        sources_list = []
        if dbt_snippet:
            sources_list.append({'origin': 'dbt_description',
                                 'ref': (fact or {}).get('token', tok_l),
                                 'snippet': dbt_snippet})
        for d in home_hits[:4]:
            sources_list.append({'origin': 'doc', 'ref': d['doc_path'],
                                 'snippet': d['snippet']})
        # Conditional severity a confirmed `differ` would carry, by agent
        # grounding model. repo-grounded (the realistic default: a coding/RAG
        # agent handed the whole repo reads the dbt project AND docs, sees both
        # sides of the contradiction, and has no rule for which wins) -> a pinned
        # term still breaks. metadata-grounded (the conservative subset: queries
        # the dbt layer only) -> a pinned term is safe, so Hygiene. With no dbt
        # pin anywhere, neither archetype has a fallback, so Blocker for both.
        # A non-dbt identifier the agent never queries is context for both.
        if fact is None:
            sev = {'repo_grounded': 'context', 'metadata_grounded': 'context'}
        elif dbt_def['exists']:
            sev = {'repo_grounded': 'blocker', 'metadata_grounded': 'hygiene'}
        else:
            sev = {'repo_grounded': 'blocker', 'metadata_grounded': 'blocker'}
        multi_home.append({
            'identifier': (fact or {}).get('token', tok_l),
            'kind': (fact or {}).get('kind', 'term'),
            'is_dbt_identifier': fact is not None,
            'authoritative_dbt_definition': dbt_def,
            'severity_if_differ': sev,
            'doc_count': n_docs,
            'sources': sources_list,
        })
    # Blocker-eligible first (no authoritative dbt fallback), then by how many
    # doc homes it has, so the LLM budget lands on reliability risks first.
    multi_home.sort(key=lambda x: (x['authoritative_dbt_definition']['exists'],
                                   -x['doc_count'], x['identifier']))

    # ── Aggregate: doc-vs-code column drift ─────────────────────────────────
    # A claimed column the model does not declare. Confidence is 'high' only
    # when the model's YAML mirrors its SQL output (count match, columns known)
    # so absence is real drift, not mere under-documentation — mirrors the
    # phantom-column confidence discipline.
    column_drift = []
    for c in all_column_claims:
        mname = c['model']
        md = models.get(mname)
        if not md:
            continue
        yaml_cols = {col['column'].lower() for col in cols_by_model.get(mname, [])}
        if not yaml_cols:
            continue  # nothing to compare against; LLM handles it
        missing = [cc for cc in c['claimed_columns']
                   if cc.lower() not in yaml_cols]
        if not missing:
            continue
        cy, cs = md.get('column_count_yaml'), md.get('column_count_sql')
        complete_mirror = bool(cy) and cy == cs
        confidence = 'high' if complete_mirror else 'provisional'
        column_drift.append({
            'doc_path': c['doc_path'],
            'model': mname,
            'claimed_not_in_model': sorted(missing),
            'model_yaml_columns': sorted(yaml_cols),
            'confidence': confidence,
            'sql_path': md.get('sql_path'),
            'yaml_path': md.get('yaml_path'),
            'snippet': c.get('snippet'),
        })
    column_drift.sort(key=lambda x: (x['confidence'] != 'high', x['model']))

    # ── LLM queue: flagged subset only, hard-capped, snippets only ──────────
    # Only multi-home candidates with NO authoritative dbt fallback are
    # Blocker-eligible: a `differ` verdict there is unanswerable, so the agent
    # must guess. Candidates the dbt layer already pins are Hygiene at most
    # (stale duplication), so synthesis handles them deterministically and they
    # never need LLM adjudication. This makes the docs LLM pass proportional to
    # real risk, not doc volume.
    eligible_multi = [m for m in multi_home
                      if not m['authoritative_dbt_definition']['exists']]
    hygiene_only_multi = len(multi_home) - len(eligible_multi)
    llm_multi = eligible_multi[:llm_cap]
    llm_claims = [
        {'doc_path': c['doc_path'], 'model': c['model'],
         'claimed_columns': c['claimed_columns'],
         'model_yaml_columns': sorted(cols_by_model_keys(cols_by_model, c['model'])),
         'snippet': c.get('snippet')}
        for c in all_column_claims][:llm_cap]
    llm_classify = [
        {'path': d['path'], 'title': d['title'], 'doc_type': d['doc_type']}
        for d in docs][:llm_cap]
    dropped_beyond_cap = {
        'multi_home': max(0, len(eligible_multi) - len(llm_multi)),
        'multi_home_hygiene_only_not_sent': hygiene_only_multi,
        'doc_column_claims': max(0, len(all_column_claims) - len(llm_claims)),
        'doc_classification': max(0, len(docs) - len(llm_classify)),
    }

    # ── Gate: is the LLM adjudication pass worth running? ────────────────────
    # The deterministic scan can produce a Blocker only via column drift or a
    # no-fallback multi-home contradiction; it produces high-value adjudication
    # only when a doc layer actually competes with dbt for authority. If none of
    # those hold, the doc corpus is non-dictionary prose (onboarding, process,
    # READMEs) and the LLM pass cannot change the verdict — skip it.
    dict_like_docs = [d['path'] for d in docs
                      if d['doc_type'] in ('glossary', 'architecture', 'runbook')]

    # Fix C: `recommended` is gated on ACTIONABLE signals only — things the LLM
    # pass can actually adjudicate. A dictionary that agrees with the dbt layer
    # has nothing to adjudicate, so "dictionary docs present" is reported as
    # context, not as a trigger. This keeps `recommended` honest: it is true iff
    # Subagent F would change the verdict.
    actionable = []
    if any(c['confidence'] == 'high' for c in column_drift):
        actionable.append('high-confidence column drift present')
    if eligible_multi:
        actionable.append(
            f'{len(eligible_multi)} no-fallback multi-home contradiction(s) to adjudicate')
    if all_column_claims:
        actionable.append(
            f'{len(all_column_claims)} doc column-claim set(s) to verify against models')

    context = []
    if dict_like_docs:
        context.append(
            f'{len(dict_like_docs)} dictionary/architecture/runbook docs present')
    if generated_docs:
        context.append(
            f'{len(generated_docs)} docs generated from the dbt manifest (drift-proof)')
    if ssot_docs:
        context.append(f'{len(ssot_docs)} docs defer authority offsite')

    llm_pass = {
        'recommended': bool(actionable),
        'reasons': actionable or [
            'nothing for the LLM pass to adjudicate: no high-confidence column '
            'drift, no no-fallback multi-home contradictions, and no doc '
            'column-claims to verify'],
        'context_signals': context,
    }

    return {
        'docs_scan_version': DOCS_SCAN_VERSION,
        'project_name': cfg.get('project_name', inventory.get('project_name')),
        'today': today.isoformat(),
        'caps': {
            'max_docs': max_docs, 'max_bytes_per_doc': max_bytes_per_doc,
            'follow_links': follow_links, 'stale_months': stale_months,
            'llm_cap': llm_cap,
        },
        'doc_corpus': {
            'total_discovered': total_discovered,
            'scanned': len(docs),
            'dropped': len(dropped),
            'dropped_sample': dropped[:10],
            'dbt_layer_excluded': dbt_layer_excluded,
            'unreadable': unreadable,
            'duplicate_content': duplicate_content,
            'discovery_root': str(discovery_root),
            'path_base': str(path_base),
            'nested_dbt_project': nested_dbt_project,
            'docs': docs,
        },
        'generated_docs': {
            'count': len(generated_docs),
            'note': ('docs render columns from the dbt manifest at build time; '
                     'they are a single source of truth and cannot drift'),
            'sample': generated_docs[:20],
        },
        'identifier_coverage': identifier_coverage,
        'llm_pass': llm_pass,
        'multi_home_candidates': multi_home,
        'column_drift': column_drift,
        'external_pointers': {
            'by_category': ext_by_cat_total,
            'total': ext_total,
            'defers_authority_offsite_docs': ssot_docs,
            'user_provided_external_sources': external_source_urls,
        },
        'staleness_flags': staleness_flags,
        'doc_column_claims': all_column_claims,
        'llm_queue': {
            'multi_home': llm_multi,
            'doc_column_claims': llm_claims,
            'doc_classification': llm_classify,
            'dropped_beyond_cap': dropped_beyond_cap,
        },
    }


def cols_by_model_keys(cols_by_model, model):
    return {c['column'] for c in cols_by_model.get(model, [])}


def _relpath(p: Path, root: Path) -> str:
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(p)


def main():
    ap = argparse.ArgumentParser(description='dbt-agent-readiness docs scanner')
    ap.add_argument('--project-path', required=True)
    ap.add_argument('--inventory', help='path to an inventory.py JSON dump; '
                    'built in-process if omitted')
    ap.add_argument('--doc-sources', nargs='*', default=None,
                    help='paths / globs / URLs outside the dbt layer')
    ap.add_argument('--max-docs', type=int, default=150)
    ap.add_argument('--max-bytes-per-doc', type=int, default=200_000)
    ap.add_argument('--follow-links', action='store_true', default=False)
    ap.add_argument('--today', default=None, help='YYYY-MM-DD (default: today)')
    ap.add_argument('--stale-months', type=int, default=18)
    ap.add_argument('--llm-cap', type=int, default=40)
    args = ap.parse_args()

    project_path = Path(args.project_path)
    if not project_path.exists():
        json.dump({'error': 'path_not_found', 'message': str(project_path)},
                  sys.stdout)
        sys.exit(1)

    try:
        if args.inventory:
            with open(args.inventory, encoding='utf-8') as f:
                inventory = json.load(f)
        else:
            inventory = inv.build_inventory(project_path)
        if 'error' in inventory:
            json.dump(inventory, sys.stdout)
            sys.exit(1)
        out = scan(
            project_path, inventory,
            doc_sources=args.doc_sources, max_docs=args.max_docs,
            max_bytes_per_doc=args.max_bytes_per_doc,
            follow_links=args.follow_links, today=_today(args.today),
            stale_months=args.stale_months, llm_cap=args.llm_cap)
    except Exception as e:
        json.dump({'error': 'docs_scan_failed', 'message': str(e)}, sys.stdout)
        sys.exit(1)

    json.dump(out, sys.stdout, indent=2, default=str)


if __name__ == '__main__':
    main()
