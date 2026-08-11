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
from .application import (
    ApplyReprocessingPlanCommand,
    ContentIntelligenceExecutionPort,
    CreateSourceImportCommand,
    SourceImportApplication,
)
from .scheduler import SourceImportScheduler
from .query import SourceImportQuery
from .execution import PostgresContentIntelligenceExecutionPort

__all__ = [
    "AnalysisTask",
    "ApplyReprocessingPlanCommand",
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
    "SourceImportApplication",
    "SourceImportScheduler",
    "SourceImportQuery",
    "SourceImportPolicy",
    "analysis_profile",
    "chunk_normalized_text",
    "diff_repository_manifests",
    "manifest_hash",
    "normalize_repository_url",
    "normalize_source_bytes",
    "plan_analysis_tasks",
]
