from __future__ import annotations

from copy import deepcopy

from novel_forge.modules.command_kernel.errors import KernelError
from .diagnostics import open_diagnoses, validate_location

CONTRACT = 'quality-review-namespaces.v1'


def separate_quality_checks(result, review, revision):
    contract = revision.get('quality_edit_contract') or {}
    if contract.get('contract_version') != 'quality-targeted-repair.v2':
        return result
    original = {item['code'] for item in open_diagnoses(review)}
    ranges = {item['code']: item for item in contract['permitted_ranges']}
    ordinary, auxiliary = [], []
    seen = set()
    observations = {item['observation']: item for item in result.get('quality_resolution_checks') or []}
    for check in result.get('resolution_checks') or []:
        code = check.get('code')
        if code in original:
            ordinary.append(check)
            continue
        target = ranges.get(code)
        observation = observations.get(target.get('observation')) if target else None
        if (not target or code in seen or not observation
                or any(check.get(k) != observation.get(k) for k in ('status', 'preservation'))
                or not str(check.get('reason') or '').strip()):
            raise KernelError('REVIEW_RESOLUTION_INVALID', 'Quality auxiliary checks must identify unique frozen ranges and agree with their independent observation')
        seen.add(code)
        validate_location(dict(check.get('evidence') or {}), str(revision['text']))
        auxiliary.append(deepcopy(check))
    if not auxiliary:
        return result
    return {**deepcopy(result), 'resolution_checks': ordinary,
            'quality_range_reassessment': {'contract_version': CONTRACT,
                'checks': auxiliary, 'original_result_preserved': True}}
