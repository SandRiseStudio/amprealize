"""MCP tool handlers for WikiService operations.

Provides handlers for wiki domains:
- research_wiki.*: Research evaluation wiki
- infra_wiki.*: Infrastructure & testing wiki
- ai_learning_wiki.*: AI/ML learning wiki
- platform_wiki.*: Amprealize platform documentation wiki

Each domain supports: ingest, query, lint, status
Research wiki adds: ingest (from evaluation)
Infra wiki adds: ingest (from source file)
AI learning wiki adds: explain, path
Platform wiki: ingest (original content), query, lint, status
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional, Tuple


def _extract_identity(params: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract owner_id, org_id, project_id from session-injected params."""
    session = params.get("_session", {})
    return (
        session.get("user_id") or params.get("user_id"),
        session.get("org_id") or params.get("org_id"),
        session.get("project_id") or params.get("project_id"),
    )


# ==============================================================================
# Research Wiki Handlers
# ==============================================================================


async def handle_research_wiki_ingest(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Ingest a research evaluation into the Research Wiki.

    Required params:
        - paper_title: Title of the evaluated paper
        - paper_id: Unique paper identifier
        - verdict: ADOPT | ADAPT | DEFER | REJECT
        - overall_score: Evaluation score (0-10)
        - markdown_report: Full evaluation report markdown

    Optional params:
        - sources: List of source references (URLs, arxiv IDs)
    """
    for required in ("paper_title", "paper_id", "verdict", "overall_score", "markdown_report"):
        if required not in params:
            return {"success": False, "error": f"Missing required parameter: {required}"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.ingest_research_evaluation(
                paper_title=params["paper_title"],
                paper_id=params["paper_id"],
                verdict=params["verdict"],
                overall_score=params["overall_score"],
                markdown_report=params["markdown_report"],
                sources=params.get("sources"),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_research_wiki_query(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Query the Research Wiki.

    Required params:
        - query: Search text

    Optional params:
        - page_type: Filter by type (entity, concept, evaluation-summary, synthesis, contradiction)
        - max_results: Maximum results (default 10)
    """
    query = params.get("query")
    if not query:
        return {"success": False, "error": "Missing required parameter: query"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.query(
                domain="research",
                query_text=query,
                page_type=params.get("page_type"),
                max_results=params.get("max_results", 10),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_research_wiki_lint(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run lint checks on the Research Wiki."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.lint("research"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_research_wiki_status(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get Research Wiki status."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.status("research"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# Infra Wiki Handlers
# ==============================================================================


async def handle_infra_wiki_ingest(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Ingest a source file into the Infra Wiki.

    Required params:
        - source_file: Repo-relative path to source file
        - page_path: Target wiki page path (e.g., "reference/run-tests-sh.md")
        - title: Page title
        - page_type: reference | howto | architecture | troubleshooting | practice
        - summary: LLM-generated documentation of the source file

    Optional params:
        - applies_to: Environments (dev, test, staging, prod)
    """
    for required in ("source_file", "page_path", "title", "page_type", "summary"):
        if required not in params:
            return {"success": False, "error": f"Missing required parameter: {required}"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.ingest_source_file(
                source_file=params["source_file"],
                page_path=params["page_path"],
                title=params["title"],
                page_type=params["page_type"],
                summary=params["summary"],
                applies_to=params.get("applies_to"),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_infra_wiki_query(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Query the Infra Wiki.

    Required params:
        - query: Search text

    Optional params:
        - page_type: Filter by type (reference, howto, architecture, troubleshooting, practice)
        - max_results: Maximum results (default 10)
    """
    query = params.get("query")
    if not query:
        return {"success": False, "error": "Missing required parameter: query"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.query(
                domain="infra",
                query_text=query,
                page_type=params.get("page_type"),
                max_results=params.get("max_results", 10),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_infra_wiki_lint(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run lint checks on the Infra Wiki."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.lint("infra"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_infra_wiki_status(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get Infra Wiki status."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.status("infra"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# AI Learning Wiki Handlers
# ==============================================================================


async def handle_ai_learning_wiki_ingest(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Ingest a new concept into the AI Learning Wiki.

    Required params:
        - page_path: Target page path (e.g., "concepts/attention-mechanism.md")
        - title: Page title
        - page_type: concept | technology | pattern | glossary | in-practice
        - body: Markdown content

    Optional params:
        - difficulty: beginner | intermediate | advanced (default: beginner)
        - prerequisites: List of prerequisite page links
        - sources: Source citations
        - amprealize_relevance: How this concept relates to Amprealize
    """
    for required in ("page_path", "title", "page_type", "body"):
        if required not in params:
            return {"success": False, "error": f"Missing required parameter: {required}"}

    extra_fm: Dict[str, Any] = {
        "difficulty": params.get("difficulty", "beginner"),
        "sources": params.get("sources", []),
    }
    if params.get("prerequisites"):
        extra_fm["prerequisites"] = params["prerequisites"]
    if params.get("amprealize_relevance"):
        extra_fm["amprealize_relevance"] = params["amprealize_relevance"]

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.create_page(
                domain="ai-learning",
                page_path=params["page_path"],
                title=params["title"],
                page_type=params["page_type"],
                body=params["body"],
                extra_frontmatter=extra_fm,
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_ai_learning_wiki_query(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Query the AI Learning Wiki.

    Required params:
        - query: Search text

    Optional params:
        - page_type: concept | technology | pattern | glossary | in-practice
        - max_results: Maximum results (default 10)
    """
    query = params.get("query")
    if not query:
        return {"success": False, "error": "Missing required parameter: query"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.query(
                domain="ai-learning",
                query_text=query,
                page_type=params.get("page_type"),
                max_results=params.get("max_results", 10),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_ai_learning_wiki_explain(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Explain an AI/ML concept using the Learning Wiki.

    Required params:
        - concept: The concept to explain
    """
    concept = params.get("concept")
    if not concept:
        return {"success": False, "error": "Missing required parameter: concept"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.explain_concept(concept),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_ai_learning_wiki_lint(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run lint checks on the AI Learning Wiki."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.lint("ai-learning"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_ai_learning_wiki_status(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get AI Learning Wiki status."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.status("ai-learning"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# General-Purpose Wiki CRUD Handlers  (wiki.*)
# ==============================================================================

_VALID_DOMAINS = {"research", "infra", "ai-learning", "platform"}


def _validate_domain(params: Dict[str, Any]) -> Optional[str]:
    domain = params.get("domain")
    if not domain or domain not in _VALID_DOMAINS:
        return None
    return domain


async def handle_wiki_read_page(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Read a wiki page by domain and path.

    Required params: domain, page_path
    """
    domain = _validate_domain(params)
    if not domain:
        return {"success": False, "error": f"Invalid domain. Must be one of: {', '.join(sorted(_VALID_DOMAINS))}"}

    page_path = params.get("page_path")
    if not page_path:
        return {"success": False, "error": "Missing required parameter: page_path"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.read_page(domain, page_path),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_wiki_create_page(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a new wiki page. Returns lint warnings after creation.

    Required params: domain, page_path, title, page_type, body
    Optional params: extra_frontmatter
    """
    domain = _validate_domain(params)
    if not domain:
        return {"success": False, "error": f"Invalid domain. Must be one of: {', '.join(sorted(_VALID_DOMAINS))}"}

    for required in ("page_path", "title", "page_type", "body"):
        if required not in params:
            return {"success": False, "error": f"Missing required parameter: {required}"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.create_page(
                domain=domain,
                page_path=params["page_path"],
                title=params["title"],
                page_type=params["page_type"],
                body=params["body"],
                extra_frontmatter=params.get("extra_frontmatter"),
            ),
        )
        # Auto-lint after creation
        if result.get("success"):
            try:
                lint_result = await loop.run_in_executor(
                    None, lambda: service.lint(domain)
                )
                warnings = lint_result.get("issues", [])
                if warnings:
                    result["lint_warnings"] = warnings
            except Exception:
                pass  # Lint failure shouldn't block create response
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_wiki_update_page(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Update an existing wiki page. Returns lint warnings after update.

    Required params: domain, page_path
    Optional params: body_additions, frontmatter_updates, replace_body
    """
    domain = _validate_domain(params)
    if not domain:
        return {"success": False, "error": f"Invalid domain. Must be one of: {', '.join(sorted(_VALID_DOMAINS))}"}

    page_path = params.get("page_path")
    if not page_path:
        return {"success": False, "error": "Missing required parameter: page_path"}

    if not params.get("body_additions") and not params.get("frontmatter_updates"):
        return {"success": False, "error": "Must provide body_additions and/or frontmatter_updates"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.update_page(
                domain=domain,
                page_path=page_path,
                body_additions=params.get("body_additions"),
                frontmatter_updates=params.get("frontmatter_updates"),
                replace_body=params.get("replace_body", False),
            ),
        )
        # Auto-lint after update
        if result.get("success"):
            try:
                lint_result = await loop.run_in_executor(
                    None, lambda: service.lint(domain)
                )
                warnings = lint_result.get("issues", [])
                if warnings:
                    result["lint_warnings"] = warnings
            except Exception:
                pass
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_wiki_delete_page(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Delete a wiki page.

    Required params: domain, page_path
    """
    domain = _validate_domain(params)
    if not domain:
        return {"success": False, "error": f"Invalid domain. Must be one of: {', '.join(sorted(_VALID_DOMAINS))}"}

    page_path = params.get("page_path")
    if not page_path:
        return {"success": False, "error": "Missing required parameter: page_path"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.delete_page(domain, page_path),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_wiki_list_pages(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """List all pages in a wiki domain with metadata.

    Required params: domain
    Optional params: page_type, folder
    """
    domain = _validate_domain(params)
    if not domain:
        return {"success": False, "error": f"Invalid domain. Must be one of: {', '.join(sorted(_VALID_DOMAINS))}"}

    filter_type = params.get("page_type")
    filter_folder = params.get("folder")

    try:
        loop = asyncio.get_event_loop()

        def _list() -> Dict[str, Any]:
            from amprealize.wiki_service import _parse_frontmatter

            wiki_dir = service._wiki_dir(domain)
            if not wiki_dir.exists():
                return {"success": True, "domain": domain, "pages": [], "total": 0}

            pages = []
            skip = {"index.md", "log.md", "overview.md", "SCHEMA.md"}

            for md_file in sorted(wiki_dir.rglob("*.md")):
                rel = str(md_file.relative_to(wiki_dir))
                if rel in skip:
                    continue

                try:
                    text = md_file.read_text(encoding="utf-8")
                except Exception:
                    continue

                fm, _ = _parse_frontmatter(text)

                folder = str(md_file.parent.relative_to(wiki_dir))
                if folder == ".":
                    folder = ""

                page_type = fm.get("type", "unknown")

                if filter_type and page_type != filter_type:
                    continue
                if filter_folder and folder != filter_folder:
                    continue

                pages.append({
                    "path": rel,
                    "title": fm.get("title", md_file.stem.replace("-", " ").title()),
                    "page_type": page_type,
                    "folder": folder,
                    "difficulty": fm.get("difficulty"),
                    "last_updated": fm.get("last_updated"),
                })

            return {"success": True, "domain": domain, "pages": pages, "total": len(pages)}

        result = await loop.run_in_executor(None, _list)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# Platform Wiki Handlers
# ==============================================================================


async def handle_platform_wiki_ingest(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Ingest a page into the Platform Wiki.

    Required params:
        - page_path: Target wiki page path (e.g., "reference/context-system.md")
        - title: Page title
        - page_type: reference | howto | architecture
        - body: Markdown content

    Optional params:
        - applies_to: Environments (dev, test, staging, prod)
        - tags: List of topic tags
    """
    for required in ("page_path", "title", "page_type", "body"):
        if required not in params:
            return {"success": False, "error": f"Missing required parameter: {required}"}

    extra_fm: Dict[str, Any] = {
        "applies_to": params.get("applies_to", ["dev", "test", "staging", "prod"]),
        "tags": params.get("tags", []),
    }

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.create_page(
                domain="platform",
                page_path=params["page_path"],
                title=params["title"],
                page_type=params["page_type"],
                body=params["body"],
                extra_frontmatter=extra_fm,
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_platform_wiki_query(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Query the Platform Wiki.

    Required params:
        - query: Search text

    Optional params:
        - page_type: Filter by type (reference, howto, architecture)
        - max_results: Maximum results (default 10)
    """
    query = params.get("query")
    if not query:
        return {"success": False, "error": "Missing required parameter: query"}

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: service.query(
                domain="platform",
                query_text=query,
                page_type=params.get("page_type"),
                max_results=params.get("max_results", 10),
            ),
        )
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_platform_wiki_lint(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Run lint checks on the Platform Wiki."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.lint("platform"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


async def handle_platform_wiki_status(
    service: Any,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """Get Platform Wiki status."""
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, lambda: service.status("platform"))
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ==============================================================================
# Handler Registries
# ==============================================================================

RESEARCH_WIKI_HANDLERS: Dict[str, Callable] = {
    "research_wiki.ingest": handle_research_wiki_ingest,
    "research_wiki.query": handle_research_wiki_query,
    "research_wiki.lint": handle_research_wiki_lint,
    "research_wiki.status": handle_research_wiki_status,
}

INFRA_WIKI_HANDLERS: Dict[str, Callable] = {
    "infra_wiki.ingest": handle_infra_wiki_ingest,
    "infra_wiki.query": handle_infra_wiki_query,
    "infra_wiki.lint": handle_infra_wiki_lint,
    "infra_wiki.status": handle_infra_wiki_status,
}

AI_LEARNING_WIKI_HANDLERS: Dict[str, Callable] = {
    "ai_learning_wiki.ingest": handle_ai_learning_wiki_ingest,
    "ai_learning_wiki.query": handle_ai_learning_wiki_query,
    "ai_learning_wiki.explain": handle_ai_learning_wiki_explain,
    "ai_learning_wiki.lint": handle_ai_learning_wiki_lint,
    "ai_learning_wiki.status": handle_ai_learning_wiki_status,
}

GENERAL_WIKI_HANDLERS: Dict[str, Callable] = {
    "wiki.read_page": handle_wiki_read_page,
    "wiki.create_page": handle_wiki_create_page,
    "wiki.update_page": handle_wiki_update_page,
    "wiki.delete_page": handle_wiki_delete_page,
    "wiki.list_pages": handle_wiki_list_pages,
}

PLATFORM_WIKI_HANDLERS: Dict[str, Callable] = {
    "platform_wiki.ingest": handle_platform_wiki_ingest,
    "platform_wiki.query": handle_platform_wiki_query,
    "platform_wiki.lint": handle_platform_wiki_lint,
    "platform_wiki.status": handle_platform_wiki_status,
}

# Combined registry for all wiki handlers
WIKI_HANDLERS: Dict[str, Callable] = {
    **RESEARCH_WIKI_HANDLERS,
    **INFRA_WIKI_HANDLERS,
    **AI_LEARNING_WIKI_HANDLERS,
    **PLATFORM_WIKI_HANDLERS,
    **GENERAL_WIKI_HANDLERS,
}
