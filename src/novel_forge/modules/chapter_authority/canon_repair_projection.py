from __future__ import annotations

from copy import deepcopy
import re

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.canon_graph.domain import PROVIDER_SEMANTIC_CHANGE_FIELDS

CONTRACT = 'canon-diagnostic-field-projection.v1'


def project_canon_repair(feedback):
    projected = deepcopy(feedback)
    diagnostic = feedback.get('diagnostic') or {}
    field = re.fullmatch(r"claim kind '.+' cannot authorize ([a-z_]+)", diagnostic.get('reason', ''))
    raw = feedback.get('rejected_output')
    if (feedback.get('contract_version') != 'chapter-canon-output-repair.v1'
            or not isinstance(raw, dict)):
        raise KernelError('CANON_REPAIR_PROJECTION_INVALID', 'Require the exact owned rejected result and diagnostic')
    if not field or diagnostic.get('code') != 'CANON_GROUNDING_INVALID':
        return projected
    selected = field[1]
    if selected not in PROVIDER_SEMANTIC_CHANGE_FIELDS.values() or selected not in raw:
        raise KernelError('CANON_REPAIR_PROJECTION_INVALID', 'The diagnosed field must exist in the rejected result')
    projected['rejected_output'] = {selected: deepcopy(raw[selected])}
    projected['feedback_selection'] = {'contract_version': CONTRACT, 'full_result_hash': snapshot_hash(raw),
        'selected_fields': [selected], 'omitted_fields': sorted(set(raw)-{selected}),
        'rule': 'Omitted feedback remains in the durable receipt. Regenerate every Canon field from the full frozen candidate and context; the host validates the complete extraction.'}
    localization = feedback.get('quote_localization') or {}
    projected['quote_localization'] = {'contract_version': localization.get('contract_version'),
        'semantic_support': 'NOT_RUN', 'full_evidence_hash': snapshot_hash(localization),
        'examples': [{'path': m['path'], 'provider_quote': m['provider_quote'], 'candidate_quote': m['candidate_quote']}
                     for m in localization.get('mappings', []) if m['path'].startswith('$.'+selected+'[')]}
    return projected
