from __future__ import annotations

from novel_forge.modules.command_kernel.errors import KernelError
from .grounding import support_kind_repair_diagnostic


def support_kind_repair_evidence(cursor, operation_id, attempt_id):
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation_output_asset oa
        JOIN authority_asset x USING(asset_id) JOIN authority_asset_version v USING(asset_version_id)
        WHERE oa.operation_id=%s AND x.asset_type='model_call_log' AND v.content->>'attempt_id'=%s
        AND v.content->>'stage'='canon_support'""", [operation_id,attempt_id])
    rows=cursor.fetchall()
    if len(rows)!=1:
        raise KernelError('CANON_SUPPORT_REPAIR_EVIDENCE_REQUIRED','Bind one exact retained independent support review')
    review=rows[0]
    cursor.execute("""SELECT v.asset_version_id,v.content_hash,v.content FROM authority_operation o,
        jsonb_array_elements(o.input_asset_snapshot) binding
        JOIN authority_asset_version v ON v.asset_version_id=binding->>'asset_version_id'
            AND v.content_hash=binding->>'content_hash'
        JOIN authority_asset x USING(asset_id)
        WHERE o.operation_id=%s AND x.asset_type='canon_extraction'""",[operation_id])
    inputs=cursor.fetchall()
    if len(inputs)!=1:
        raise KernelError('CANON_SUPPORT_REPAIR_INPUT_REQUIRED','Retain the exact frozen Canon extraction')
    extraction=inputs[0]
    result=review[2].get('provider_evidence',{}).get('production_execution',{}).get('process_evidence',{}).get('result')
    proof=support_kind_repair_diagnostic(extraction[2],result) if isinstance(result,dict) else None
    if not proof:
        raise KernelError('CANON_GROUNDING_REEXTRACTION_REQUIRED','Unsupported, uncertain or mismatched defined kinds require semantic repair')
    return {**proof,'review_asset':{'asset_version_id':review[0],'content_hash':review[1]},
        'extraction_asset':{'asset_version_id':extraction[0],'content_hash':extraction[1]}}
