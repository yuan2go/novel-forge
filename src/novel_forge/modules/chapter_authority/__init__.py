"""PostgreSQL-authoritative single-chapter application slice."""

from novel_forge.modules.chapter_authority.application import ChapterAuthorityApplication

from novel_forge.modules.chapter_authority.contracts import (
    ChapterHandlerOutput,
    ChapterHandlerRegistry,
    ChapterInputAsset,
    ChapterNode,
)
from novel_forge.modules.chapter_authority.definitions import (
    CHAPTER_SLICE_DEFINITION_VERSION,
    CHAPTER_MODEL_EFFECT_DEFINITION_VERSION,
    CHAPTER_SLICE_ROOT_DEFINITION_NAME,
    chapter_root_operation_definition,
    chapter_operation_definitions,
)
from novel_forge.modules.chapter_authority.evidence import (
    build_chapter_slice_evidence_manifest,
)
from novel_forge.modules.chapter_authority.handlers import (
    DeterministicFixtureChapterProvider,
    build_chapter_handler_registry,
)
from novel_forge.modules.chapter_authority.model_effects import (
    ChapterModelPort,
    ChapterModelExternalEffectAdapter,
    ChapterModelRoute,
    ExternalEffectChapterModelPort,
    ModelProviderResult,
)
from novel_forge.modules.chapter_authority.export_delivery import (
    ExportDeliveryEvidence,
)
from novel_forge.modules.chapter_authority.orchestrator import (
    ChapterSliceResult,
    SingleChapterRequest,
    run_single_chapter_slice,
)
from novel_forge.modules.chapter_authority.queries import ChapterAuthorityQuery

__all__ = [
    "CHAPTER_SLICE_DEFINITION_VERSION",
    "CHAPTER_MODEL_EFFECT_DEFINITION_VERSION",
    "CHAPTER_SLICE_ROOT_DEFINITION_NAME",
    "ChapterHandlerOutput",
    "ChapterHandlerRegistry",
    "ChapterInputAsset",
    "ChapterNode",
    "ChapterModelPort",
    "ChapterModelExternalEffectAdapter",
    "ChapterModelRoute",
    "ChapterSliceResult",
    "ChapterAuthorityQuery",
    "ChapterAuthorityApplication",
    "DeterministicFixtureChapterProvider",
    "ExportDeliveryEvidence",
    "ExternalEffectChapterModelPort",
    "ModelProviderResult",
    "SingleChapterRequest",
    "build_chapter_handler_registry",
    "build_chapter_slice_evidence_manifest",
    "chapter_root_operation_definition",
    "chapter_operation_definitions",
    "run_single_chapter_slice",
]
