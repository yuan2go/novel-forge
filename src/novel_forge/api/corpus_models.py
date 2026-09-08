from pydantic import BaseModel, ConfigDict

from novel_forge.modules.source_authority.corpus import CorpusAction, Text


class CorpusCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: Text
    workspace_id: Text
    idempotency_key: Text
    action: CorpusAction
    trace_id: str = ""
    correlation_id: str = ""
