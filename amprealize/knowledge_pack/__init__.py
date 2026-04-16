"""Knowledge Pack system — portable, versioned expertise bundles for Amprealize.

See docs/AMPREALIZE_KNOWLEDGE_PACK_ARCHITECTURE.md for full design.
"""

from amprealize.knowledge_pack.builder import (
    KnowledgePackArtifact,
    PackBuilder,
    PackBuildConfig,
)
from amprealize.knowledge_pack.overlay_rules import (
    OverlayClassifier,
    Role,
    RoleClassificationRule,
    Surface,
    SurfaceClassificationRule,
    TaskClassificationRule,
    TaskFamily,
    default_classifier,
    filter_overlays_by_role,
    filter_overlays_by_surface,
    filter_overlays_by_task,
)
from amprealize.knowledge_pack.extractor import (
    BehaviorFragment,
    DoctrineFragment,
    ExtractionResult,
    PlaybookFragment,
    SourceExtractor,
)
from amprealize.knowledge_pack.schema import (
    KnowledgePackManifest,
    OverlayFragment,
    OverlayKind,
    PackConstraints,
    PackScope,
    PackSource,
    PackSourceType,
    SourceScope,
    ValidationResult,
    LintIssue,
)
from amprealize.knowledge_pack.source_registry import (
    DriftResult,
    RegisterSourceRequest,
    SourceNotFoundError,
    SourceRecord,
    SourceRegistryError,
    SourceRegistryService,
)
from amprealize.knowledge_pack.storage import (
    KnowledgePackStorage,
    PackNotFoundError,
    PackStorageError,
    PackVersionExistsError,
)

__all__ = [
    "BehaviorFragment",
    "DoctrineFragment",
    "DriftResult",
    "ExtractionResult",
    "KnowledgePackArtifact",
    "KnowledgePackManifest",
    "KnowledgePackStorage",
    "LintIssue",
    "OverlayClassifier",
    "OverlayFragment",
    "OverlayKind",
    "PackBuilder",
    "PackBuildConfig",
    "PackConstraints",
    "PackNotFoundError",
    "PackScope",
    "PackSource",
    "PackSourceType",
    "PackStorageError",
    "PackVersionExistsError",
    "PlaybookFragment",
    "RegisterSourceRequest",
    "Role",
    "RoleClassificationRule",
    "SourceExtractor",
    "SourceNotFoundError",
    "SourceRecord",
    "SourceRegistryError",
    "SourceRegistryService",
    "SourceScope",
    "Surface",
    "SurfaceClassificationRule",
    "TaskClassificationRule",
    "TaskFamily",
    "ValidationResult",
    "default_classifier",
    "filter_overlays_by_role",
    "filter_overlays_by_surface",
    "filter_overlays_by_task",
]
