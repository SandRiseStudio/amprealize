"""Pydantic models for Knowledge Pack manifests, overlays, and sources.

Implements the data model from architecture doc section 7.1 / 7.2.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PackSourceType(str, Enum):
    """How a pack source is referenced."""

    FILE = "file"
    SERVICE = "service"


class SourceScope(str, Enum):
    """Knowledge tier for a source (architecture doc §5.1)."""

    CANONICAL = "canonical"
    OPERATIONAL = "operational"
    SURFACE = "surface"
    RUNTIME = "runtime"


class PackScope(str, Enum):
    """Where a pack is activated."""

    WORKSPACE = "workspace"
    GLOBAL = "global"


class OverlayKind(str, Enum):
    """Overlay classification axis."""

    TASK = "task"
    SURFACE = "surface"
    ROLE = "role"


# ---------------------------------------------------------------------------
# Semver helper
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z\-]+(?:\.[0-9A-Za-z\-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z\-]+(?:\.[0-9A-Za-z\-]+)*))?$"
)

_PACK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class PackSource(BaseModel):
    """A single source contributing to a knowledge pack (architecture §7.1)."""

    type: PackSourceType
    ref: str = Field(..., min_length=1, description="File path or service key")
    scope: SourceScope = SourceScope.CANONICAL
    conditional: bool = False
    version_hash: Optional[str] = None


class PackConstraints(BaseModel):
    """Enforcement rules embedded in a pack manifest."""

    strict_role_declaration: bool = False
    strict_behavior_citation: bool = False
    mandatory_overlays: List[str] = Field(default_factory=list)


class OverlayFragment(BaseModel):
    """A reusable instruction overlay keyed to task/surface/role (architecture §7.2)."""

    overlay_id: str = Field(..., min_length=1)
    kind: OverlayKind
    applies_to: Dict[str, Any] = Field(default_factory=dict)
    instructions: List[str] = Field(default_factory=list)
    retrieval_keywords: List[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0)

    @field_validator("overlay_id")
    @classmethod
    def _validate_overlay_id(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9][a-z0-9\-]*$", v):
            raise ValueError(
                f"overlay_id must be lowercase alphanumeric with hyphens, got '{v}'"
            )
        return v


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


class KnowledgePackManifest(BaseModel):
    """Top-level pack descriptor (architecture §7.1)."""

    pack_id: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    scope: PackScope = PackScope.WORKSPACE
    workspace_profiles: List[str] = Field(default_factory=list)
    surfaces: List[str] = Field(default_factory=list)
    sources: List[PackSource] = Field(default_factory=list)
    doctrine_fragments: List[str] = Field(default_factory=list)
    behavior_refs: List[str] = Field(default_factory=list)
    task_overlays: List[str] = Field(default_factory=list)
    surface_overlays: List[str] = Field(default_factory=list)
    constraints: PackConstraints = Field(default_factory=PackConstraints)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None

    @field_validator("pack_id")
    @classmethod
    def _validate_pack_id(cls, v: str) -> str:
        if not _PACK_ID_RE.match(v):
            raise ValueError(
                f"pack_id must be lowercase alphanumeric with hyphens, got '{v}'"
            )
        return v

    @field_validator("version")
    @classmethod
    def _validate_version(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(f"version must be valid semver, got '{v}'")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to JSON-safe dict."""
        return self.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


class LintIssue(BaseModel):
    """A single linting issue found in a manifest."""

    level: str = Field(..., pattern=r"^(error|warning|info)$")
    path: str = Field(default="", description="JSON path to the problematic field")
    message: str = ""


class ValidationResult(BaseModel):
    """Outcome of manifest validation."""

    valid: bool = True
    errors: List[LintIssue] = Field(default_factory=list)
    warnings: List[LintIssue] = Field(default_factory=list)
