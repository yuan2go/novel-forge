"""Source execution port that materializes exact governed analysis Skills."""
from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
from typing import Any

from novel_forge.infrastructure.environment import RuntimeEnvironment
from novel_forge.modules.capability_packs.artifacts import ArtifactKind, ArtifactResolver
from novel_forge.modules.chapter_authority.execution_gateway import (
    ProductionExecutionGatewayExternalEffectAdapter,
)
from novel_forge.modules.source_authority.deconstruction import stable_hash

from .artifacts import source_intelligence_artifact_resolver
from .execution import PostgresContentIntelligenceExecutionPort as _BaseExecutionPort


class PostgresContentIntelligenceExecutionPort(_BaseExecutionPort):
    """Uses repository-governed Skill content in the shared Source PEP route."""

    def __init__(
        self,
        database_url: str,
        *,
        transport: ProductionExecutionGatewayExternalEffectAdapter,
        worker_id: str,
        lease_seconds: int = 60,
        max_cost_per_call: str = "0",
        budget_caps: Mapping[str, str] | None = None,
        artifact_resolver: ArtifactResolver | None = None,
    ) -> None:
        super().__init__(
            database_url,
            transport=transport,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            max_cost_per_call=max_cost_per_call,
            budget_caps=budget_caps,
        )
        self.source_artifact_resolver = artifact_resolver or self._default_resolver()

    @staticmethod
    def _default_resolver() -> ArtifactResolver | None:
        environment = RuntimeEnvironment.parse(
            str(os.environ.get("NOVEL_FORGE_ENVIRONMENT") or "development")
        )
        configured_root = str(os.environ.get("NOVEL_FORGE_ROOT") or "").strip()
        root = (
            Path(configured_root).expanduser().resolve()
            if configured_root
            else Path(__file__).resolve().parents[4]
        )
        try:
            return source_intelligence_artifact_resolver(root)
        except (OSError, UnicodeError, ValueError) as exc:
            if environment.controlled:
                raise RuntimeError(
                    "controlled Source intelligence requires exact governed Skill artifacts"
                ) from exc
            return None

    def _materialization(self, spec: Any) -> dict[str, Any]:
        materialization = super()._materialization(spec)
        if self.source_artifact_resolver is None:
            return materialization
        artifact = self.source_artifact_resolver.resolve(
            ArtifactKind.SKILL,
            str(spec.skill_id),
            str(spec.skill_version),
        )
        content = json.loads(artifact.content_json)
        text = str(content.get("text") or "") if isinstance(content, dict) else ""
        if not text.strip():
            raise ValueError("governed Source Skill artifact has no text content")
        materialization["skill"] = {
            "ref": artifact.ref,
            "version": artifact.version,
            "content_hash": artifact.content_hash,
            "source_identity": artifact.source_identity,
            "text": text,
        }
        materialization.pop("materialization_hash", None)
        materialization["materialization_hash"] = stable_hash(materialization)
        return materialization


__all__ = ["PostgresContentIntelligenceExecutionPort"]
