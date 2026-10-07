from __future__ import annotations

from copy import deepcopy
import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.review.diagnostics import prose_hash, validate_location

CONTRACT = 'canon-quote-localization.v1'
GLYPHS = str.maketrans({'‘': '"', '’': '"', '“': '"', '”': '"'})


def localize_provider_quotes(document, *, text, target_asset_version_id):
    result = deepcopy(document)
    mappings = []

    def locate(value, path, start=None, end=None):
        if not isinstance(value, str) or not value or value in text:
            return value
        folded, source = value.translate(GLYPHS), text.translate(GLYPHS)
        position = source.find(folded)
        if position < 0 or source.find(folded, position + 1) >= 0:
            raise KernelError('CANON_QUOTE_LOCALIZATION_INVALID', 'Require one complete quote-glyph-only match in the exact candidate')
        limit = position + len(value)
        if ((start is not None or end is not None) and (start, end) != (position, limit)):
            raise KernelError('CANON_QUOTE_LOCALIZATION_INVALID', 'Explicit evidence offsets cannot be moved')
        actual = text[position:limit]
        differences = [{'offset': i, 'provider': a, 'candidate': b} for i, (a,b) in enumerate(zip(value, actual, strict=True)) if a != b]
        if not differences or any(ord(d['provider']) not in GLYPHS or ord(d['candidate']) not in GLYPHS for d in differences):
            raise KernelError('CANON_QUOTE_LOCALIZATION_INVALID', 'Do not normalize words, whitespace, ASCII quotes or other punctuation')
        location = validate_location({'quote': actual, 'start': position, 'end': limit}, text)
        mappings.append({'path': path, 'provider_quote': value, 'candidate_quote': actual,
            'differences': differences, 'location': location, 'status': 'LOCALIZED',
            'original_literal_check': 'FAILED', 'semantic_support': 'NOT_RUN'})
        return actual

    def walk(value, path):
        if isinstance(value, dict):
            for key in ('evidence_quote', 'quote'):
                if key in value:
                    prefix = 'evidence_' if key == 'evidence_quote' else ''
                    value[key] = locate(value[key], path+'.'+key, value.get(prefix+'start'), value.get(prefix+'end'))
            if isinstance(value.get('resolution_evidence'), list):
                for i, ref in enumerate(value['resolution_evidence']):
                    if isinstance(ref, str):
                        legacy = re.fullmatch(r'chars:(\d+)-(\d+):(.+)', ref)
                        if legacy:
                            start, end = int(legacy[1]), int(legacy[2])
                            quote = locate(legacy[3], path+f'.resolution_evidence[{i}]', start, end)
                            value['resolution_evidence'][i] = f'chars:{start}-{end}:{quote}'
                        else:
                            value['resolution_evidence'][i] = locate(ref, path+f'.resolution_evidence[{i}]')
            for key, child in value.items():
                walk(child, path+'.'+key)
        elif isinstance(value, list):
            for i, child in enumerate(value):
                walk(child, path+f'[{i}]')
    walk(result, '$')
    return result, {'contract_version': CONTRACT, 'target_asset_version_id': target_asset_version_id,
        'target_text_hash': prose_hash(text), 'mappings': mappings,
        'provider_literal_result_preserved': True, 'strict_certification_eligible': False,
        'semantic_support': 'NOT_RUN'}
