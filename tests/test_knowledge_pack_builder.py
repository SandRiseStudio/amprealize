"""Tests for the Knowledge Pack builder (Phase C Step 8).

Covers PackBuilder.build(), _generate_primer(), _assemble_overlays(),
_generate_retrieval_metadata(), and the PackBuildConfig/KnowledgePackArtifact
dataclasses.
"""

from __future__ import annotations

import pytest

from amprealize.knowledge_pack.builder import (
    KnowledgePackArtifact,
    PackBuildConfig,
    PackBuilder,
    _collect_keywords,
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
)
from amprealize.knowledge_pack.source_registry import (
    SourceRecord,
    SourceRegistryService,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------


class FakeRegistry:
    """Minimal stub replacing SourceRegistryService for unit tests."""

    def __init__(self, sources: list[SourceRecord] | None = None):
        self._sources = sources or []

    def list_sources(self) -> list[SourceRecord]:
        return list(self._sources)


class FakeExtractor:
    """Minimal stub replacing SourceExtractor for unit tests."""

    def __init__(self, result: ExtractionResult | None = None):
        self._result = result or ExtractionResult()

    def extract_all(self, sources):
        return self._result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_source(ref: str = "AGENTS.md", scope: str = "canonical") -> SourceRecord:
    return SourceRecord(
        source_id="src-1",
        source_type="file",
        ref=ref,
        scope=scope,
        owner=None,
        version_hash="abc123",
        generation_eligible=True,
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )


def _make_behavior(name: str = "behavior_test", desc: str = "Do something") -> BehaviorFragment:
    return BehaviorFragment(
        fragment_id=f"frag-{name}",
        source_ref="AGENTS.md",
        behavior_name=name,
        description=desc,
        instruction=f"Always {desc.lower()}",
        trigger_keywords=["test", name.split("_")[-1]],
        role_focus="STUDENT",
        tags=["testing"],
    )


def _make_doctrine(heading: str = "Rules", content: str = "Use MCP tools") -> DoctrineFragment:
    return DoctrineFragment(
        fragment_id=f"frag-{heading.lower().replace(' ', '-')}",
        source_ref="AGENTS.md",
        section_heading=heading,
        content=content,
        scope="canonical",
        role_applicability=["student"],
        surface_applicability=["vscode"],
        retrieval_keywords=["mcp", "tools"],
    )


def _make_playbook(heading: str = "Setup", content: str = "Run amprealize init") -> PlaybookFragment:
    return PlaybookFragment(
        fragment_id=f"frag-pb-{heading.lower()}",
        source_ref="ops_playbook.md",
        section_heading=heading,
        content=content,
        scope="operational",
        role_applicability=["student"],
        surface_applicability=["cli"],
        retrieval_keywords=["setup"],
    )


def _make_config(**overrides) -> PackBuildConfig:
    defaults = {
        "pack_id": "test-pack",
        "version": "0.1.0",
        "workspace_profiles": ["solo-dev"],
        "target_surfaces": ["vscode", "cli"],
    }
    defaults.update(overrides)
    return PackBuildConfig(**defaults)


# ---------------------------------------------------------------------------
# PackBuildConfig tests
# ---------------------------------------------------------------------------


class TestPackBuildConfig:
    def test_defaults(self):
        cfg = PackBuildConfig(pack_id="p", version="1.0.0")
        assert cfg.workspace_profiles == []
        assert cfg.target_surfaces == []
        assert cfg.source_filter is None
        assert cfg.created_by is None

    def test_custom_values(self):
        cfg = _make_config(created_by="agent")
        assert cfg.pack_id == "test-pack"
        assert cfg.created_by == "agent"


# ---------------------------------------------------------------------------
# KnowledgePackArtifact tests
# ---------------------------------------------------------------------------


class TestKnowledgePackArtifact:
    def test_to_dict(self):
        manifest = KnowledgePackManifest(
            pack_id="p",
            version="1.0.0",
        )
        overlay = OverlayFragment(
            overlay_id="role-student",
            kind=OverlayKind.ROLE,
            instructions=["Do X"],
        )
        artifact = KnowledgePackArtifact(
            manifest=manifest,
            primer_text="primer",
            overlays=[overlay],
            retrieval_metadata={"entries": []},
            build_log=["started"],
        )
        d = artifact.to_dict()
        assert d["primer_text"] == "primer"
        assert d["manifest"]["pack_id"] == "p"
        assert len(d["overlays"]) == 1
        assert d["build_log"] == ["started"]


# ---------------------------------------------------------------------------
# Primer generation tests
# ---------------------------------------------------------------------------


class TestGeneratePrimer:
    def _builder(self, **kwargs):
        return PackBuilder(
            registry=FakeRegistry(),
            extractor=FakeExtractor(),
            **kwargs,
        )

    def test_empty_fragments_produces_minimal_primer(self):
        b = self._builder()
        primer = b._generate_primer([], [], [])
        assert "Amprealize runtime context:" in primer
        assert "Please apply the relevant Amprealize guidance" in primer

    def test_profile_included(self):
        b = self._builder()
        primer = b._generate_primer([], [], [], profile="amprealize-platform")
        assert "Workspace profile: amprealize-platform" in primer

    def test_behaviors_listed_alphabetically(self):
        b = self._builder()
        bfs = [
            _make_behavior("behavior_z", "Zzz last"),
            _make_behavior("behavior_a", "Aaa first"),
        ]
        primer = b._generate_primer([], bfs, [])
        assert "Relevant behaviors:" in primer
        idx_a = primer.index("behavior_a")
        idx_z = primer.index("behavior_z")
        assert idx_a < idx_z, "behaviors should be sorted alphabetically"

    def test_doctrine_guidance_included(self):
        b = self._builder()
        dfs = [_make_doctrine("Rules", "Always use structured logging for production")]
        primer = b._generate_primer(dfs, [], [])
        assert "Relevant operational guidance:" in primer
        assert "Always use structured logging" in primer

    def test_playbook_guidance_included(self):
        b = self._builder()
        pfs = [_make_playbook("Setup", "Run amprealize init before first build")]
        primer = b._generate_primer([], [], pfs)
        assert "Run amprealize init before first build" in primer

    def test_long_descriptions_truncated(self):
        b = self._builder()
        long_desc = "A" * 200
        bfs = [_make_behavior("behavior_long", long_desc)]
        primer = b._generate_primer([], bfs, [])
        assert "..." in primer

    def test_budget_enforced(self):
        b = self._builder(primer_char_budget=100)
        bfs = [_make_behavior(f"behavior_{i}", f"Desc {i}") for i in range(50)]
        primer = b._generate_primer([], bfs, [])
        assert len(primer) <= 100

    def test_truncation_on_line_boundary(self):
        text = "line one\nline two\nline three\nline four"
        result = PackBuilder._truncate_to_budget(text, 25)
        assert "\n" not in result or result.endswith("two")
        assert len(result) <= 25


# ---------------------------------------------------------------------------
# Overlay assembly tests
# ---------------------------------------------------------------------------


class TestAssembleOverlays:
    def _builder(self):
        return PackBuilder(
            registry=FakeRegistry(),
            extractor=FakeExtractor(),
        )

    def test_role_overlays_created(self):
        b = self._builder()
        extraction = ExtractionResult(
            behavior_fragments=[
                _make_behavior("behavior_a", "A desc"),
                _make_behavior("behavior_b", "B desc"),
            ]
        )
        manifest = KnowledgePackManifest(pack_id="p", version="1.0.0")
        overlays = b._assemble_overlays(extraction, manifest)
        role_overlays = [o for o in overlays if o.kind == OverlayKind.ROLE]
        assert len(role_overlays) >= 1
        assert role_overlays[0].overlay_id.startswith("role-")

    def test_surface_overlays_created(self):
        b = self._builder()
        extraction = ExtractionResult(
            doctrine_fragments=[_make_doctrine("Rules", "Use MCP tools")],
        )
        manifest = KnowledgePackManifest(
            pack_id="p", version="1.0.0", surfaces=["vscode"]
        )
        overlays = b._assemble_overlays(extraction, manifest)
        surface_overlays = [o for o in overlays if o.kind == OverlayKind.SURFACE]
        assert len(surface_overlays) == 1
        assert surface_overlays[0].overlay_id == "surface-vscode"

    def test_task_overlay_from_operational_doctrine(self):
        b = self._builder()
        extraction = ExtractionResult(
            doctrine_fragments=[
                DoctrineFragment(
                    fragment_id="frag-ops",
                    source_ref="AGENTS.md",
                    section_heading="Etiquette",
                    content="Run pytest after changes",
                    scope="operational",
                    retrieval_keywords=["testing"],
                )
            ]
        )
        manifest = KnowledgePackManifest(pack_id="p", version="1.0.0")
        overlays = b._assemble_overlays(extraction, manifest)
        task_overlays = [o for o in overlays if o.kind == OverlayKind.TASK]
        assert len(task_overlays) == 1
        assert task_overlays[0].overlay_id == "task-general"

    def test_no_surface_overlay_when_no_match(self):
        b = self._builder()
        extraction = ExtractionResult(
            doctrine_fragments=[
                DoctrineFragment(
                    fragment_id="frag-1",
                    source_ref="AGENTS.md",
                    section_heading="X",
                    content="something",
                    scope="canonical",
                    surface_applicability=["cli"],
                )
            ]
        )
        manifest = KnowledgePackManifest(
            pack_id="p", version="1.0.0", surfaces=["web"]
        )
        overlays = b._assemble_overlays(extraction, manifest)
        surface_overlays = [o for o in overlays if o.kind == OverlayKind.SURFACE]
        assert len(surface_overlays) == 0

    def test_empty_extraction_produces_no_overlays(self):
        b = self._builder()
        extraction = ExtractionResult()
        manifest = KnowledgePackManifest(pack_id="p", version="1.0.0")
        overlays = b._assemble_overlays(extraction, manifest)
        assert overlays == []


# ---------------------------------------------------------------------------
# Retrieval metadata tests
# ---------------------------------------------------------------------------


class TestRetrievalMetadata:
    def _builder(self):
        return PackBuilder(
            registry=FakeRegistry(),
            extractor=FakeExtractor(),
        )

    def test_entries_match_overlays(self):
        b = self._builder()
        overlays = [
            OverlayFragment(
                overlay_id="role-student",
                kind=OverlayKind.ROLE,
                instructions=["Do X"],
                retrieval_keywords=["student"],
            ),
            OverlayFragment(
                overlay_id="surface-cli",
                kind=OverlayKind.SURFACE,
                instructions=["Use CLI"],
                retrieval_keywords=["cli"],
            ),
        ]
        meta = b._generate_retrieval_metadata(overlays)
        assert len(meta["entries"]) == 2
        ids = {e["overlay_id"] for e in meta["entries"]}
        assert ids == {"role-student", "surface-cli"}

    def test_embedding_text_from_instructions(self):
        b = self._builder()
        overlays = [
            OverlayFragment(
                overlay_id="task-general",
                kind=OverlayKind.TASK,
                instructions=["Run pytest", "Check coverage"],
            ),
        ]
        meta = b._generate_retrieval_metadata(overlays)
        entry = meta["entries"][0]
        assert "Run pytest" in entry["embedding_text"]
        assert "Check coverage" in entry["embedding_text"]

    def test_empty_overlays(self):
        b = self._builder()
        meta = b._generate_retrieval_metadata([])
        assert meta["entries"] == []


# ---------------------------------------------------------------------------
# Full build pipeline tests
# ---------------------------------------------------------------------------


class TestBuildPipeline:
    def test_full_build_produces_artifact(self):
        source = _make_source()
        extraction = ExtractionResult(
            behavior_fragments=[_make_behavior()],
            doctrine_fragments=[_make_doctrine()],
        )
        builder = PackBuilder(
            registry=FakeRegistry([source]),
            extractor=FakeExtractor(extraction),
        )
        config = _make_config()
        artifact = builder.build(config)

        assert isinstance(artifact, KnowledgePackArtifact)
        assert artifact.manifest.pack_id == "test-pack"
        assert artifact.manifest.version == "0.1.0"
        assert len(artifact.primer_text) > 0
        assert len(artifact.build_log) >= 4  # start, sources, fragments, finish at minimum

    def test_source_filter_limits_sources(self):
        s1 = _make_source(ref="AGENTS.md")
        s2 = SourceRecord(
            source_id="src-2",
            source_type="file",
            ref="playbook.md",
            scope="operational",
            owner=None,
            version_hash="def456",
            generation_eligible=True,
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
        )
        builder = PackBuilder(
            registry=FakeRegistry([s1, s2]),
            extractor=FakeExtractor(),
        )
        config = _make_config(source_filter=["playbook.md"])
        artifact = builder.build(config)
        # Manifest sources should only contain the filtered one
        refs = [s.ref for s in artifact.manifest.sources]
        assert refs == ["playbook.md"]

    def test_overlay_ids_backfilled_to_manifest(self):
        extraction = ExtractionResult(
            behavior_fragments=[_make_behavior()],
            doctrine_fragments=[
                DoctrineFragment(
                    fragment_id="frag-ops",
                    source_ref="AGENTS.md",
                    section_heading="Ops",
                    content="Run checks",
                    scope="operational",
                )
            ],
        )
        builder = PackBuilder(
            registry=FakeRegistry([_make_source()]),
            extractor=FakeExtractor(extraction),
        )
        config = _make_config(target_surfaces=["vscode"])
        artifact = builder.build(config)
        # task_overlays should have task-general
        assert "task-general" in artifact.manifest.task_overlays

    def test_build_with_no_sources(self):
        builder = PackBuilder(
            registry=FakeRegistry([]),
            extractor=FakeExtractor(),
        )
        config = _make_config()
        artifact = builder.build(config)
        assert artifact.manifest.sources == []
        assert "Sources resolved: 0" in artifact.build_log[1]

    def test_extraction_errors_in_build_log(self):
        extraction = ExtractionResult(errors=["Failed to parse foo.md"])
        builder = PackBuilder(
            registry=FakeRegistry([_make_source()]),
            extractor=FakeExtractor(extraction),
        )
        config = _make_config()
        artifact = builder.build(config)
        assert any("Extraction warning" in line for line in artifact.build_log)

    def test_created_by_propagated(self):
        builder = PackBuilder(
            registry=FakeRegistry([_make_source()]),
            extractor=FakeExtractor(),
        )
        config = _make_config(created_by="agent-test")
        artifact = builder.build(config)
        assert artifact.manifest.created_by == "agent-test"

    def test_to_dict_round_trip(self):
        extraction = ExtractionResult(
            behavior_fragments=[_make_behavior()],
        )
        builder = PackBuilder(
            registry=FakeRegistry([_make_source()]),
            extractor=FakeExtractor(extraction),
        )
        config = _make_config()
        artifact = builder.build(config)
        d = artifact.to_dict()
        assert isinstance(d, dict)
        assert "manifest" in d
        assert "primer_text" in d
        assert "overlays" in d


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestCollectKeywords:
    def test_merges_keywords(self):
        bfs = [
            _make_behavior("behavior_a", "A"),
            _make_behavior("behavior_b", "B"),
        ]
        # Override trigger keywords for test
        bfs[0] = BehaviorFragment(
            fragment_id="f1",
            source_ref="x",
            behavior_name="a",
            description="",
            instruction="",
            trigger_keywords=["mcp", "tool"],
        )
        bfs[1] = BehaviorFragment(
            fragment_id="f2",
            source_ref="x",
            behavior_name="b",
            description="",
            instruction="",
            trigger_keywords=["mcp", "logging"],
        )
        kws = _collect_keywords(bfs)
        assert "mcp" in kws
        assert "tool" in kws
        assert "logging" in kws
        # No duplicates
        assert kws.count("mcp") == 1

    def test_respects_limit(self):
        bf = BehaviorFragment(
            fragment_id="f",
            source_ref="x",
            behavior_name="n",
            description="",
            instruction="",
            trigger_keywords=[f"kw{i}" for i in range(50)],
        )
        kws = _collect_keywords([bf], limit=5)
        assert len(kws) == 5
