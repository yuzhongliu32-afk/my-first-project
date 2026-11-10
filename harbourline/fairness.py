"""Bias and fairness check on the resident consultation (Brief: governance stretch; Deliverable 4).

Counts only what each response records (age band, language, channel, block, rating). It never
infers age, language, disability or identity from comment text, never treats frequency as
priority, and has no population denominator, so it reports coverage, not representativeness.
"""
from __future__ import annotations

import csv
import io
from collections import Counter
from statistics import mean

GROUPS = ('age_band', 'language', 'channel', 'block')
MIN_GROUP_FOR_MEAN = 10
LOW_SHARE = 0.05
DOC_HINT = 'CONSULT'


def _consultation_doc(library):
    docs = [d for d in library.documents if DOC_HINT in d['document_id'].upper()]
    return docs[0] if docs else None


def fairness_check(library) -> dict | None:
    """Return a FairnessCheck record (Full schema) for the consultation file, or None if absent."""
    doc = _consultation_doc(library)
    if doc is None:
        return None
    rows = list(csv.DictReader(io.StringIO('\n'.join(doc['lines']))))
    n = len(rows)
    findings = [f'Observed responses: {n}. Counts describe responses, not the estate population; '
                'no population denominator or sampling weights are supplied.']
    ids = Counter(r.get('response_id') for r in rows)
    dups = sorted(k for k, v in ids.items() if k and v > 1)
    findings.append(f'Duplicate response IDs: {len(dups)}' + (f' ({", ".join(dups[:10])})' if dups else '') + '.')
    missing = {col: sum(1 for r in rows if not (r.get(col) or '').strip()) for col in (rows[0].keys() if rows else [])}
    gaps = {k: v for k, v in missing.items() if v}
    findings.append('Missing values: ' + (', '.join(f'{k} {v}' for k, v in gaps.items()) if gaps else 'none') + '.')
    low = []
    for g in GROUPS:
        counts = Counter((r.get(g) or 'missing').strip() or 'missing' for r in rows)
        findings.append(f'{g}: ' + ', '.join(f'{k} {v} ({v / n:.0%})' for k, v in sorted(counts.items())) + '.')
        low += [f'{g}={k} ({v})' for k, v in counts.items() if n and v / n < LOW_SHARE]
        if g in ('age_band', 'language'):
            means = []
            for k in sorted(counts):
                vals = [float(r['rating_1to5']) for r in rows if (r.get(g) or '').strip() == k
                        and (r.get('rating_1to5') or '').strip().replace('.', '', 1).isdigit()]
                means.append(f'{k} {mean(vals):.2f} (n={len(vals)})' if len(vals) >= MIN_GROUP_FOR_MEAN
                             else f'{k} not compared (n={len(vals)} < {MIN_GROUP_FOR_MEAN})')
            findings.append(f'Mean rating by {g}: ' + '; '.join(means) + '.')
    if low:
        findings.append('Low-coverage groups (under 5% of responses): ' + ', '.join(low) +
                        '. Their views can be outweighed in any frequency-based summary.')
    offline = sum(1 for r in rows if (r.get('channel') or '').strip() in ('paper', 'townhall'))
    non_en = sum(1 for r in rows if (r.get('language') or '').strip() not in ('', 'en'))
    findings.append(f'Offline responses (paper or town hall): {offline}; recorded non-English responses: {non_en}. '
                    'Original-language comments are preserved; translation meaning needs human review.')
    header = library.ref(doc, 1, 1)
    return {
        'check_id': 'FAIR-' + doc['version'][:12],
        'method': ('Coverage counts by recorded age band, language, channel and block; duplicate and '
                   'missing-value audit; mean rating compared only for groups with at least '
                   f'{MIN_GROUP_FOR_MEAN} responses. No demographic inference from comment text; '
                   'frequency is not treated as priority.'),
        'source_snapshot_id': library.snapshot,
        'groups_considered': list(GROUPS),
        'findings': findings,
        'mitigation_actions': [
            'A named human reviewer compares minority, offline, senior and non-English themes with the consultation summary.',
            'Keep accessibility and low-frequency objections alongside majority themes; do not infer consensus.',
            'Obtain estate population denominators before any claim of representativeness.',
            'Do not mark the fairness review approved until a human has signed it off.',
        ],
        'source_refs': [header],
    }
