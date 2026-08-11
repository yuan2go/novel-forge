"""Canonical PostgreSQL Source Import runtime."""

from .domain import (
    ManifestDiffEntry,
    NormalizedChunk,
    NormalizedSource,
    RepositoryFile,
    SourceImportPolicy,
    chunk_normalized_text,
    diff_repository_manifests,
    manifest_hash,
    normalize_repository_url,
    normalize_source_bytes,
)
from .git_adapter import GitRepositoryExternalEffectAdapter
from .object_reader import LocalObjectStoreReader, MinioObjectStoreReader
from .analysis_profiles import (
    AnalysisTask,
    SourceAnalysisProfile,
    analysis_profile,
    plan_analysis_tasks,
)
from .content_profile import (
    CLASSIFIER_VERSION,
    SourceContentProfile,
    classify_source_content,
)
from .application import (
    ApplyReprocessingPlanCommand,
    ContentIntelligenceExecutionPort,
    CreateSourceImportCommand,
)
from .routed_application import SourceImportApplication
from .scheduler import SourceImportScheduler
from .query import SourceImportQuery
from .execution import PostgresContentIntelligenceExecutionPort

__all__ = [
    "AnalysisTask",
    "ApplyReprocessingPlanCommand",
    "CLASSIFIER_VERSION",
    "ContentIntelligenceExecutionPort",
    "CreateSourceImportCommand",
    "GitRepositoryExternalEffectAdapter",
    "LocalObjectStoreReader",
    "ManifestDiffEntry",
    "MinioObjectStoreReader",
    "NormalizedChunk",
    "NormalizedSource",
    "PostgresContentIntelligenceExecutionPort",
    "RepositoryFile",
    "SourceAnalysisProfile",
    "SourceContentProfile",
    "SourceImportApplication",
    "SourceImportScheduler",
    "SourceImportQuery",
    "SourceImportPolicy",
    "analysis_profile",
    "chunk_normalized_text",
    "classify_source_content",
    "diff_repository_manifests",
    "manifest_hash",
    "normalize_repository_url",
    "normalize_source_bytes",
    "plan_analysis_tasks",
]
