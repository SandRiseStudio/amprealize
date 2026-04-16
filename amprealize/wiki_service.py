"""Wiki service for managing LLM-maintained wiki pages.

Provides CRUD operations, querying, and lint for domain-scoped wikis:
- Research Wiki (wiki/research/) — AI research evaluations
- Infra Wiki (wiki/infra/) — infrastructure & testing knowledge
- AI Learning Wiki (wiki/ai-learning/) — AI/ML educational content
- Platform Wiki (wiki/platform/) — Amprealize platform documentation

Wiki pages are markdown files with YAML frontmatter, stored in git.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIKI_DOMAINS = ("research", "infra", "ai-learning", "platform")

SPECIAL_FILES = {"index.md", "log.md", "overview.md", "SCHEMA.md"}

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split a markdown file into frontmatter dict and body text."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    body = text[m.end():]
    return fm, body


def _render_frontmatter(fm: Dict[str, Any]) -> str:
    """Render a frontmatter dict to YAML block."""
    return "---\n" + yaml.dump(fm, default_flow_style=False, sort_keys=False).rstrip() + "\n---\n"


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _git_short_hash(file_path: str, repo_root: str) -> Optional[str]:
    """Get short git hash for a file, or None if not tracked."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h", "--", file_path],
            capture_output=True, text=True, cwd=repo_root, timeout=5,
        )
        h = result.stdout.strip()
        return h if h else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# WikiService
# ---------------------------------------------------------------------------


class WikiService:
    """Manages three domain-scoped LLM wikis stored as markdown in git."""

    def __init__(self, repo_root: Optional[str] = None):
        """Initialize WikiService.

        Args:
            repo_root: Root of the repository containing wiki/ directories.
                       Defaults to current working directory.
        """
        self._repo_root = Path(repo_root) if repo_root else Path.cwd()
        self._wiki_base = self._repo_root / "wiki"

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _wiki_dir(self, domain: str) -> Path:
        if domain not in WIKI_DOMAINS:
            raise ValueError(f"Unknown wiki domain: {domain}. Must be one of {WIKI_DOMAINS}")
        return self._wiki_base / domain

    def _resolve_page_path(self, domain: str, page_path: str) -> Path:
        """Resolve a page path relative to the wiki domain directory.

        Prevents path traversal by ensuring the resolved path stays within the wiki.
        """
        wiki_dir = self._wiki_dir(domain)
        resolved = (wiki_dir / page_path).resolve()
        if not str(resolved).startswith(str(wiki_dir.resolve())):
            raise ValueError(f"Invalid page path: {page_path} (path traversal blocked)")
        return resolved

    # ------------------------------------------------------------------
    # CRUD Operations
    # ------------------------------------------------------------------

    def create_page(
        self,
        domain: str,
        page_path: str,
        title: str,
        page_type: str,
        body: str,
        extra_frontmatter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a new wiki page with frontmatter.

        Args:
            domain: Wiki domain (research, infra, ai-learning)
            page_path: Path relative to wiki/<domain>/ (e.g., "entities/faiss.md")
            title: Page title
            page_type: Page type (entity, concept, reference, howto, etc.)
            body: Markdown body content
            extra_frontmatter: Additional frontmatter fields

        Returns:
            Dict with success status and page metadata.
        """
        path = self._resolve_page_path(domain, page_path)

        if path.exists():
            return {"success": False, "error": f"Page already exists: {page_path}"}

        fm: Dict[str, Any] = {
            "title": title,
            "type": page_type,
            "last_updated": _today(),
        }
        if extra_frontmatter:
            fm.update(extra_frontmatter)

        path.parent.mkdir(parents=True, exist_ok=True)
        content = _render_frontmatter(fm) + "\n" + body.lstrip("\n")
        path.write_text(content, encoding="utf-8")

        # Update index and log
        self._add_to_index(domain, page_path, title, page_type)
        self._append_log(domain, "create", f"Created {page_path}: {title}")

        return {
            "success": True,
            "page_path": page_path,
            "domain": domain,
            "title": title,
            "type": page_type,
        }

    def update_page(
        self,
        domain: str,
        page_path: str,
        body_additions: Optional[str] = None,
        frontmatter_updates: Optional[Dict[str, Any]] = None,
        replace_body: bool = False,
    ) -> Dict[str, Any]:
        """Update an existing wiki page.

        Args:
            domain: Wiki domain
            page_path: Path relative to wiki/<domain>/
            body_additions: Text to append to body (or replace if replace_body=True)
            frontmatter_updates: Fields to update in frontmatter
            replace_body: If True, replace body entirely instead of appending
        """
        path = self._resolve_page_path(domain, page_path)

        if not path.exists():
            return {"success": False, "error": f"Page not found: {page_path}"}

        text = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        if frontmatter_updates:
            fm.update(frontmatter_updates)
        fm["last_updated"] = _today()

        if body_additions:
            if replace_body:
                body = body_additions
            else:
                body = body.rstrip() + "\n\n" + body_additions.lstrip("\n")

        path.write_text(_render_frontmatter(fm) + "\n" + body.lstrip("\n"), encoding="utf-8")

        self._append_log(domain, "update", f"Updated {page_path}")

        return {"success": True, "page_path": page_path, "domain": domain}

    def read_page(self, domain: str, page_path: str) -> Dict[str, Any]:
        """Read a wiki page, returning frontmatter and body separately."""
        path = self._resolve_page_path(domain, page_path)

        if not path.exists():
            return {"success": False, "error": f"Page not found: {page_path}"}

        text = path.read_text(encoding="utf-8")
        fm, body = _parse_frontmatter(text)

        return {
            "success": True,
            "page_path": page_path,
            "domain": domain,
            "frontmatter": fm,
            "body": body.strip(),
        }

    def delete_page(self, domain: str, page_path: str) -> Dict[str, Any]:
        """Delete a wiki page."""
        if page_path in SPECIAL_FILES or page_path == "SCHEMA.md":
            return {"success": False, "error": f"Cannot delete special file: {page_path}"}

        path = self._resolve_page_path(domain, page_path)

        if not path.exists():
            return {"success": False, "error": f"Page not found: {page_path}"}

        path.unlink()
        self._append_log(domain, "delete", f"Deleted {page_path}")

        return {"success": True, "page_path": page_path, "domain": domain}

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self,
        domain: str,
        query_text: str,
        page_type: Optional[str] = None,
        max_results: int = 10,
    ) -> Dict[str, Any]:
        """Search wiki pages by scanning index and page content.

        Uses simple keyword matching against index.md and page content.
        Will upgrade to FAISS when any wiki exceeds ~200 pages.
        """
        wiki_dir = self._wiki_dir(domain)
        results: List[Dict[str, Any]] = []
        query_lower = query_text.lower()
        terms = query_lower.split()

        for md_file in wiki_dir.rglob("*.md"):
            rel = md_file.relative_to(wiki_dir)
            if str(rel) in SPECIAL_FILES or rel.name == "SCHEMA.md":
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            fm, body = _parse_frontmatter(text)

            if page_type and fm.get("type") != page_type:
                continue

            # Simple relevance scoring: count term hits in title + body
            searchable = (fm.get("title", "") + " " + body).lower()
            hits = sum(1 for t in terms if t in searchable)
            if hits == 0:
                continue

            results.append({
                "page_path": str(rel),
                "title": fm.get("title", rel.stem),
                "type": fm.get("type", "unknown"),
                "score": hits / len(terms),
                "snippet": body[:200].strip(),
                "last_updated": fm.get("last_updated"),
            })

        results.sort(key=lambda r: r["score"], reverse=True)
        results = results[:max_results]

        return {
            "success": True,
            "domain": domain,
            "query": query_text,
            "results": results,
            "total_matches": len(results),
        }

    def status(self, domain: str) -> Dict[str, Any]:
        """Get wiki status: page counts by type, last update, total pages."""
        wiki_dir = self._wiki_dir(domain)
        if not wiki_dir.exists():
            return {"success": False, "error": f"Wiki directory not found: {domain}"}

        type_counts: Dict[str, int] = {}
        total = 0
        latest_update: Optional[str] = None

        for md_file in wiki_dir.rglob("*.md"):
            rel = md_file.relative_to(wiki_dir)
            if str(rel) in SPECIAL_FILES or rel.name == "SCHEMA.md":
                continue

            total += 1
            try:
                text = md_file.read_text(encoding="utf-8")
                fm, _ = _parse_frontmatter(text)
                pt = fm.get("type", "unknown")
                type_counts[pt] = type_counts.get(pt, 0) + 1
                lu = fm.get("last_updated")
                if lu and (latest_update is None or str(lu) > str(latest_update)):
                    latest_update = str(lu)
            except Exception:
                type_counts["unknown"] = type_counts.get("unknown", 0) + 1

        return {
            "success": True,
            "domain": domain,
            "total_pages": total,
            "pages_by_type": type_counts,
            "last_updated": latest_update,
        }

    # ------------------------------------------------------------------
    # Lint
    # ------------------------------------------------------------------

    def lint(self, domain: str) -> Dict[str, Any]:
        """Run lint checks on a wiki domain.

        Returns issues found: broken links, missing frontmatter, orphans, staleness.
        """
        wiki_dir = self._wiki_dir(domain)
        if not wiki_dir.exists():
            return {"success": False, "error": f"Wiki directory not found: {domain}"}

        issues: List[Dict[str, Any]] = []
        all_pages: set = set()
        linked_pages: set = set()

        # Collect all pages
        for md_file in wiki_dir.rglob("*.md"):
            rel = str(md_file.relative_to(wiki_dir))
            if rel in SPECIAL_FILES or md_file.name == "SCHEMA.md":
                continue
            all_pages.add(rel)

        # Check each page
        for md_file in wiki_dir.rglob("*.md"):
            rel = str(md_file.relative_to(wiki_dir))
            if rel in SPECIAL_FILES or md_file.name == "SCHEMA.md":
                continue

            try:
                text = md_file.read_text(encoding="utf-8")
            except Exception as e:
                issues.append({"rule": "unreadable", "severity": "error", "page": rel, "message": str(e)})
                continue

            fm, body = _parse_frontmatter(text)

            # Missing frontmatter
            required = {"title", "type", "last_updated"}
            if domain == "research":
                required.add("sources")
                required.add("confidence")
            elif domain == "infra":
                required.update({"source_files", "source_hash", "applies_to"})
            elif domain == "ai-learning":
                required.update({"difficulty", "sources"})
            elif domain == "platform":
                required.update({"applies_to", "tags"})

            missing = required - set(fm.keys())
            if missing:
                issues.append({
                    "rule": "missing-frontmatter",
                    "severity": "error",
                    "page": rel,
                    "message": f"Missing required fields: {', '.join(sorted(missing))}",
                })

            # Broken links
            for match in re.finditer(r'\[([^\]]*)\]\(([^)]+)\)', body):
                link_target = match.group(2)
                if link_target.startswith("http") or link_target.startswith("#"):
                    continue
                # Resolve relative to page location
                page_dir = md_file.parent
                resolved = (page_dir / link_target).resolve()
                if not resolved.exists():
                    issues.append({
                        "rule": "broken-link",
                        "severity": "error",
                        "page": rel,
                        "message": f"Broken link: [{match.group(1)}]({link_target})",
                    })
                else:
                    # Track linked pages for orphan detection
                    try:
                        linked_rel = str(resolved.relative_to(wiki_dir))
                        linked_pages.add(linked_rel)
                    except ValueError:
                        pass  # Cross-wiki link

            # Empty sections
            for section_match in re.finditer(r'^(#{1,4}\s+.+)\n\n(#{1,4}\s+|\Z)', body, re.MULTILINE):
                issues.append({
                    "rule": "empty-section",
                    "severity": "info",
                    "page": rel,
                    "message": f"Empty section: {section_match.group(1).strip()}",
                })

            # Domain-specific staleness checks
            if domain == "infra" and fm.get("source_hash") and isinstance(fm["source_hash"], dict):
                for src_file, stored_hash in fm["source_hash"].items():
                    current_hash = _git_short_hash(src_file, str(self._repo_root))
                    if current_hash and current_hash != stored_hash:
                        issues.append({
                            "rule": "stale-source",
                            "severity": "warning",
                            "page": rel,
                            "message": f"Source {src_file} changed: {stored_hash} → {current_hash}",
                        })

        # Orphan detection
        orphans = all_pages - linked_pages
        # Check index.md for references
        index_path = wiki_dir / "index.md"
        index_text = ""
        if index_path.exists():
            index_text = index_path.read_text(encoding="utf-8").lower()

        for orphan in orphans:
            if orphan.lower() not in index_text:
                issues.append({
                    "rule": "orphan-page",
                    "severity": "warning",
                    "page": orphan,
                    "message": "Page not linked from any other page or index.md",
                })

        return {
            "success": True,
            "domain": domain,
            "total_issues": len(issues),
            "issues": issues,
            "issues_by_severity": {
                "error": sum(1 for i in issues if i["severity"] == "error"),
                "warning": sum(1 for i in issues if i["severity"] == "warning"),
                "info": sum(1 for i in issues if i["severity"] == "info"),
            },
        }

    # ------------------------------------------------------------------
    # Research Wiki: Ingest from evaluation
    # ------------------------------------------------------------------

    def ingest_research_evaluation(
        self,
        paper_title: str,
        paper_id: str,
        verdict: str,
        overall_score: float,
        markdown_report: str,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest a research evaluation into the Research Wiki.

        Extracts entities and concepts from the report, creates/updates pages,
        and updates index + log.

        Args:
            paper_title: Title of the evaluated paper
            paper_id: Unique identifier
            verdict: ADOPT/ADAPT/DEFER/REJECT
            overall_score: Evaluation score (0-10)
            markdown_report: Full evaluation report markdown
            sources: Source references (URLs, arxiv IDs)
        """
        domain = "research"
        created_pages: List[str] = []
        updated_pages: List[str] = []

        # 1. Create evaluation summary page
        slug = re.sub(r'[^a-z0-9]+', '-', paper_title.lower()).strip('-')[:60]
        eval_path = f"evaluations/{slug}.md"
        confidence = "high" if overall_score >= 7 else ("medium" if overall_score >= 4 else "low")

        eval_body = f"# {paper_title}\n\n"
        eval_body += f"**Verdict**: {verdict} | **Score**: {overall_score}/10\n\n"

        # Extract executive summary from report if present
        exec_match = re.search(r'(?:Executive Summary|## Summary)\s*\n(.*?)(?=\n##|\Z)', markdown_report, re.DOTALL | re.IGNORECASE)
        if exec_match:
            eval_body += "## Key Findings\n\n" + exec_match.group(1).strip() + "\n"

        result = self.create_page(
            domain=domain,
            page_path=eval_path,
            title=f"Evaluation: {paper_title}",
            page_type="evaluation-summary",
            body=eval_body,
            extra_frontmatter={
                "sources": sources or [paper_id],
                "confidence": confidence,
                "tags": [verdict.lower()],
            },
        )
        if result["success"]:
            created_pages.append(eval_path)

        # 2. Extract entities and concepts (simple extraction from report)
        entities, concepts = self._extract_entities_and_concepts(markdown_report)

        for entity_name, entity_desc in entities:
            entity_slug = re.sub(r'[^a-z0-9]+', '-', entity_name.lower()).strip('-')
            entity_path = f"entities/{entity_slug}.md"
            full_path = self._resolve_page_path(domain, entity_path)

            if full_path.exists():
                # Update existing page with new reference
                self.update_page(
                    domain=domain,
                    page_path=entity_path,
                    body_additions=f"\n### From: {paper_title}\n\n{entity_desc}\n",
                    frontmatter_updates={"confidence": confidence},
                )
                updated_pages.append(entity_path)
            else:
                self.create_page(
                    domain=domain,
                    page_path=entity_path,
                    title=entity_name,
                    page_type="entity",
                    body=f"# {entity_name}\n\n{entity_desc}\n\n## Evaluation History\n\n- [{paper_title}](../evaluations/{slug}.md) — {verdict} ({overall_score}/10)\n",
                    extra_frontmatter={
                        "sources": sources or [paper_id],
                        "confidence": confidence,
                        "tags": [],
                    },
                )
                created_pages.append(entity_path)

        for concept_name, concept_desc in concepts:
            concept_slug = re.sub(r'[^a-z0-9]+', '-', concept_name.lower()).strip('-')
            concept_path = f"concepts/{concept_slug}.md"
            full_path = self._resolve_page_path(domain, concept_path)

            if full_path.exists():
                self.update_page(
                    domain=domain,
                    page_path=concept_path,
                    body_additions=f"\n### From: {paper_title}\n\n{concept_desc}\n",
                )
                updated_pages.append(concept_path)
            else:
                self.create_page(
                    domain=domain,
                    page_path=concept_path,
                    title=concept_name,
                    page_type="concept",
                    body=f"# {concept_name}\n\n{concept_desc}\n",
                    extra_frontmatter={
                        "sources": sources or [paper_id],
                        "confidence": confidence,
                        "tags": [],
                    },
                )
                created_pages.append(concept_path)

        # 3. Cross-wiki: Auto-create AI Learning concept stubs for new concepts
        learning_concepts_created: List[str] = []
        for concept_name, concept_desc in concepts:
            concept_slug = re.sub(r'[^a-z0-9]+', '-', concept_name.lower()).strip('-')
            learning_path = f"concepts/{concept_slug}.md"
            learning_full = self._resolve_page_path("ai-learning", learning_path)

            if not learning_full.exists() and self._wiki_dir("ai-learning").exists():
                stub_body = (
                    f"# {concept_name}\n\n"
                    f"> *Auto-generated from research evaluation of [{paper_title}]"
                    f"(../../research/evaluations/{slug}.md).*\n\n"
                    f"{concept_desc}\n\n"
                    f"## Why This Matters\n\n"
                    f"*TODO: Add intuitive explanation.*\n\n"
                    f"## How It Works\n\n"
                    f"*TODO: Add technical detail.*\n"
                )
                result = self.create_page(
                    domain="ai-learning",
                    page_path=learning_path,
                    title=concept_name,
                    page_type="concept",
                    body=stub_body,
                    extra_frontmatter={
                        "difficulty": "intermediate",
                        "sources": sources or [paper_id],
                        "amprealize_relevance": f"Discovered via research evaluation: {paper_title}",
                    },
                )
                if result.get("success"):
                    learning_concepts_created.append(learning_path)

        return {
            "success": True,
            "domain": domain,
            "paper_title": paper_title,
            "created_pages": created_pages,
            "updated_pages": updated_pages,
            "total_changes": len(created_pages) + len(updated_pages),
            "cross_wiki_learning_concepts": learning_concepts_created,
        }

    def _extract_entities_and_concepts(
        self, report: str
    ) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
        """Extract entities and concepts from a research report.

        Uses pattern matching on the report markdown to find:
        - Entities: tools, frameworks, models, labs mentioned with descriptions
        - Concepts: techniques, patterns, architectural approaches

        Returns (entities, concepts) where each is a list of (name, description) tuples.
        """
        entities: List[Tuple[str, str]] = []
        concepts: List[Tuple[str, str]] = []

        # Extract from competitive landscape section
        landscape_match = re.search(
            r'(?:Competitive Landscape|## Alternatives|## Related)\s*\n(.*?)(?=\n## |\Z)',
            report, re.DOTALL | re.IGNORECASE
        )
        if landscape_match:
            section = landscape_match.group(1)
            for item in re.finditer(r'[-*]\s+\*?\*?([^*:\n]+?)\*?\*?\s*[:\-–]\s*(.+?)(?=\n[-*]|\Z)', section, re.DOTALL):
                name = item.group(1).strip()
                desc = item.group(2).strip()[:200]
                if len(name) > 2 and len(name) < 60:
                    entities.append((name, desc))

        # Extract concepts from key findings / methodology sections
        for section_name in ["Key Concepts", "Methodology", "Technical Approach", "Architecture", "Core Idea"]:
            concept_match = re.search(
                rf'(?:{section_name})\s*\n(.*?)(?=\n## |\Z)',
                report, re.DOTALL | re.IGNORECASE
            )
            if concept_match:
                section = concept_match.group(1)
                for item in re.finditer(r'[-*]\s+\*?\*?([^*:\n]+?)\*?\*?\s*[:\-–]\s*(.+?)(?=\n[-*]|\Z)', section, re.DOTALL):
                    name = item.group(1).strip()
                    desc = item.group(2).strip()[:200]
                    if len(name) > 2 and len(name) < 60:
                        concepts.append((name, desc))

        return entities, concepts

    # ------------------------------------------------------------------
    # Infra Wiki: Ingest from source files
    # ------------------------------------------------------------------

    def ingest_source_file(
        self,
        source_file: str,
        page_path: str,
        title: str,
        page_type: str,
        summary: str,
        applies_to: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Ingest a source file into the Infra Wiki.

        Args:
            source_file: Repo-relative path to the source file
            page_path: Target wiki page path (e.g., "reference/run-tests-sh.md")
            title: Page title
            page_type: Page type (reference, howto, etc.)
            summary: LLM-generated summary/documentation of the source file
            applies_to: Environments this applies to (dev, test, staging, prod)
        """
        domain = "infra"
        source_hash = _git_short_hash(source_file, str(self._repo_root))

        extra_fm: Dict[str, Any] = {
            "source_files": [source_file],
            "source_hash": {source_file: source_hash or "unknown"},
            "applies_to": applies_to or ["dev", "test"],
        }

        full_path = self._resolve_page_path(domain, page_path)
        if full_path.exists():
            return self.update_page(
                domain=domain,
                page_path=page_path,
                body_additions=summary,
                frontmatter_updates=extra_fm,
                replace_body=True,
            )
        else:
            return self.create_page(
                domain=domain,
                page_path=page_path,
                title=title,
                page_type=page_type,
                body=summary,
                extra_frontmatter=extra_fm,
            )

    # ------------------------------------------------------------------
    # AI Learning Wiki: explain
    # ------------------------------------------------------------------

    def explain_concept(self, concept: str) -> Dict[str, Any]:
        """Look up a concept in the AI Learning Wiki and return the explanation.

        Searches concept pages, glossary, and patterns for the best match.
        """
        result = self.query("ai-learning", concept, max_results=3)
        if not result["success"] or not result["results"]:
            return {
                "success": False,
                "error": f"No wiki page found for concept: {concept}",
                "suggestion": "This concept may not have been ingested yet.",
            }

        best = result["results"][0]
        page = self.read_page("ai-learning", best["page_path"])
        if not page["success"]:
            return page

        return {
            "success": True,
            "concept": concept,
            "title": page["frontmatter"].get("title", concept),
            "difficulty": page["frontmatter"].get("difficulty", "unknown"),
            "prerequisites": page["frontmatter"].get("prerequisites", []),
            "explanation": page["body"],
            "amprealize_relevance": page["frontmatter"].get("amprealize_relevance"),
        }

    # ------------------------------------------------------------------
    # Private: index and log maintenance
    # ------------------------------------------------------------------

    def _add_to_index(self, domain: str, page_path: str, title: str, page_type: str) -> None:
        """Add a page entry to the domain's index.md."""
        index_path = self._wiki_dir(domain) / "index.md"
        if not index_path.exists():
            return

        text = index_path.read_text(encoding="utf-8")

        # Find the section matching the page type and add the entry
        entry = f"- [{title}]({page_path})\n"

        # Map page types to section headers
        section_map = {
            # Research
            "entity": "## Entities",
            "concept": "## Concepts",
            "evaluation-summary": "## Evaluation Summaries",
            "synthesis": "## Synthesis",
            "contradiction": "## Contradictions",
            # Infra
            "reference": "## Reference",
            "howto": "## How-To",
            "architecture": "## Architecture",
            "troubleshooting": "## Troubleshooting",
            "practice": "## Practices",
            # AI Learning
            "technology": "## Technologies",
            "pattern": "## Patterns",
            "glossary": "## Glossary",
            "in-practice": "## In Practice",
        }

        section_header = section_map.get(page_type, "## Other")

        if section_header in text:
            # Find the section and add after the placeholder or last entry
            placeholder = f"_No {page_type} pages yet._"
            if placeholder in text:
                text = text.replace(placeholder, entry.rstrip())
            else:
                # Add after section header's content
                idx = text.index(section_header)
                next_section = text.find("\n## ", idx + len(section_header))
                if next_section == -1:
                    text = text.rstrip() + "\n" + entry
                else:
                    text = text[:next_section].rstrip() + "\n" + entry + "\n" + text[next_section:]
        else:
            text = text.rstrip() + f"\n\n{section_header}\n\n{entry}"

        index_path.write_text(text, encoding="utf-8")

    def _append_log(self, domain: str, operation: str, details: str) -> None:
        """Append an entry to the domain's log.md."""
        log_path = self._wiki_dir(domain) / "log.md"
        if not log_path.exists():
            return

        text = log_path.read_text(encoding="utf-8")
        entry = f"| {_now_iso()} | {operation} | {details} |\n"
        text = text.rstrip() + "\n" + entry

        log_path.write_text(text, encoding="utf-8")
