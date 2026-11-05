"""Portable versioned evidence shared by A, B and C; no inferred issue dates."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import re
import math
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class EvidenceLibrary:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.bundle = json.loads(self.path.read_text(encoding='utf-8'))
        self.documents = self.bundle['documents']
        material = {k: v for k, v in self.bundle.items() if k != 'source_snapshot_id'}
        if self.bundle['source_snapshot_id'] != 'SRC-' + digest(material)[:20]:
            raise ValueError('Source content changed without a new snapshot. Rebuild the library.')
        self.semantic_path = None
        self.snapshot = self.bundle['source_snapshot_id']
        identities = [(d['document_id'], d['version']) for d in self.documents]
        if len(set(identities)) != len(identities):
            raise ValueError('Duplicate evidence document version')
        for d in self.documents:
            if len(d['lines']) != len(d['line_pages']):
                raise ValueError('Line/page map length mismatch')
            if d.get('available_from'):
                date.fromisoformat(d['available_from'])

    def line_registry(self):
        return {(d['document_id'], d['version']): d['lines'] for d in self.documents}

    def ref(self, doc, start, end):
        pages = set(doc['line_pages'][start-1:end])
        if len(pages) != 1:
            raise ValueError('Reference crosses physical page boundary')
        return {'document_id': doc['document_id'], 'document_version': doc['version'],
                'source_type': doc['source_type'], 'page': next(iter(pages)), 'line_start': start,
                'line_end': end, 'chunk_id': f"{doc['document_id']}:{start}-{end}",
                'quote': '\n'.join(doc['lines'][start-1:end])}

    def verify(self, ref, cutoff=None):
        matches = [d for d in self.documents if (d['document_id'], d['version']) == (ref['document_id'], ref['document_version'])]
        if len(matches) != 1:
            raise ValueError('Unloaded evidence version')
        d = matches[0]; start, end = ref['line_start'], ref['line_end']
        if not isinstance(start, int) or not isinstance(end, int) or not 1 <= start <= end <= len(d['lines']):
            raise ValueError('Evidence lines out of range')
        expected = self.ref(d, start, end)
        # Single-line B references strip PDF layout whitespace; do not allow other rewriting.
        quote = expected['quote'].strip() if start == end else expected['quote']
        if ref['quote'] not in (expected['quote'], quote) or ref['page'] != expected['page'] or ref['source_type'] != expected['source_type']:
            raise ValueError('Citation does not match source text/page/type')
        if cutoff and not self.eligible(d, start, end, cutoff):
            raise ValueError('Future or unknown-date evidence is not eligible')
        return True

    def eligible(self, doc, start, end, cutoff):
        if not cutoff:
            return True
        date.fromisoformat(cutoff)
        segments = doc.get('dated_segments', [])
        if segments:
            covering = [s for s in segments if s['line_start'] <= start and end <= s['line_end']]
            return len(covering) == 1 and covering[0]['available_from'] <= cutoff
        if doc.get('background_only'):
            return True  # Explicit static baseline; never report as period progress.
        return bool(doc.get('available_from')) and doc['available_from'] <= cutoff

    def search(self, query, cutoff=None, limit=12, gateway=None):
        if self.semantic_path:
            return self.semantic_search(query,cutoff,limit,gateway)
        words = set(re.findall(r'[a-z0-9]+', query.lower()))
        ranked = []
        for doc in self.documents:
            for index, line in enumerate(doc['lines'], 1):
                if not line.strip() or not self.eligible(doc, index, index, cutoff):
                    continue
                score = len(words & set(re.findall(r'[a-z0-9]+', line.lower())))
                if score:
                    ranked.append((score, doc['document_id'], index, self.ref(doc, index, index)))
        ranked.sort(key=lambda r: (-r[0], r[1], r[2]))
        return [r[3] for r in ranked[:limit]]

    def semantic_search(self,query,cutoff,limit,gateway):
        if gateway is None:raise ValueError('Semantic retrieval requires a model gateway')
        index=json.loads(Path(self.semantic_path).read_text())
        if index['source_snapshot_id']!=self.snapshot:raise ValueError('Semantic index is stale; rebuild it')
        eligible=[]
        for chunk in index['chunks']:
            try:self.verify(chunk['source'],cutoff)
            except ValueError:continue
            eligible.append(chunk)
        if not eligible:return []
        vector=gateway.embeddings([query],index['model'])[0]
        def cosine(v):
            if len(v)!=len(vector) or not all(math.isfinite(x) for x in v+vector):raise ValueError('Invalid embedding dimensions or values')
            denominator=math.sqrt(sum(x*x for x in v)*sum(x*x for x in vector))
            return sum(x*y for x,y in zip(v,vector))/denominator if denominator else 0
        return [c['source'] for c in sorted(eligible,key=lambda c:cosine(c['vector']),reverse=True)[:limit]]


def build_library(records, output, *, metadata=None, b_snapshot='BRIEF-2026-10-10-ONLY'):
    metadata = metadata or {}
    docs = []
    for record in records:
        info = metadata.get(record['document_id'], {})
        lines = record['lines']
        d = {'document_id': record['document_id'], 'version': record['version'],
             'source_type': record['source_type'], 'lines': lines,
             'line_pages': record.get('line_pages', [record.get('page')] * len(lines)),
             'available_from': info.get('available_from'),
             'background_only': info.get('background_only', record['source_type'] == 'BRIEF'),
             'dated_segments': info.get('dated_segments', [])}
        if d['dated_segments']:
            prev = 0
            for seg in sorted(d['dated_segments'], key=lambda s:s['line_start']):
                if not 1 <= seg['line_start'] <= seg['line_end'] <= len(lines) or seg['line_start'] <= prev:
                    raise ValueError('Invalid or overlapping evidence dated segments')
                date.fromisoformat(seg['available_from']); prev = seg['line_end']
        docs.append(d)
    bundle = {'format_version': 'harbourline-evidence.v1', 'b_source_mode': b_snapshot,
              'retrieval_method': 'deterministic lexical line retrieval',
              'documents': sorted(docs, key=lambda d:(d['document_id'], d['version']))}
    bundle['source_snapshot_id'] = 'SRC-' + digest(bundle)[:20]
    target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(bundle, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return EvidenceLibrary(target)
