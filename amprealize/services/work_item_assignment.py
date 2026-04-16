"""
Auto-assignment logic for work items.

When work items are created, this service can automatically assign them to:
1. The most relevant AI agent based on capabilities and context
2. The project owner/admin if no relevant agent is found
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from amprealize.boards.contracts import (
    AssigneeType,
    AssignWorkItemRequest,
    WorkItem,
    WorkItemType,
)
from amprealize.projects.contracts import Agent, AgentStatus
from amprealize.services.board_service import Actor, BoardService

logger = logging.getLogger(__name__)


# Keywords that map to agent capabilities/types
CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
    "engineering": ["code", "implement", "build", "develop", "refactor", "test", "fix", "bug", "feature", "api", "backend", "frontend", "database", "schema", "migration"],
    "architecture": ["architect", "design", "adr", "pattern", "infrastructure", "system", "scalability", "performance"],
    "research": ["research", "analyze", "investigate", "study", "evaluate", "paper", "literature", "survey"],
    "product": ["product", "requirement", "user story", "acceptance criteria", "prd", "spec", "feature", "roadmap"],
    "data_science": ["data", "analytics", "ml", "machine learning", "model", "dataset", "metrics", "dashboard"],
    "security": ["security", "auth", "authentication", "authorization", "vulnerability", "threat", "compliance"],
    "devops": ["deploy", "ci/cd", "pipeline", "container", "kubernetes", "docker", "infrastructure", "monitoring"],
    "documentation": ["document", "docs", "readme", "guide", "tutorial", "api docs", "reference"],
}


def _extract_context_keywords(work_item: WorkItem) -> List[str]:
    """Extract relevant keywords from work item title and description."""
    text = f"{work_item.title} {work_item.description or ''}".lower()
    # Normalize text
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    return list(set(words))


def _score_agent_for_work_item(agent: Agent, work_item: WorkItem) -> Tuple[float, str]:
    """
    Score how well an agent matches a work item based on capabilities.

    Returns:
        Tuple of (score, reason)
    """
    if agent.status != AgentStatus.ACTIVE:
        return 0.0, "agent not active"

    keywords = _extract_context_keywords(work_item)

    # Check agent capabilities against capability keywords
    agent_caps = set(cap.lower() for cap in agent.capabilities)
    score = 0.0
    matched_caps = []

    for capability, cap_keywords in CAPABILITY_KEYWORDS.items():
        if capability in agent_caps:
            # Check if work item contains keywords for this capability
            matches = [kw for kw in cap_keywords if kw in keywords]
            if matches:
                score += len(matches) * 2.0  # Weight for matching capability keywords
                matched_caps.append(capability)

    # Also check agent name for hints
    agent_name_lower = agent.name.lower()
    for capability, cap_keywords in CAPABILITY_KEYWORDS.items():
        if any(kw in agent_name_lower for kw in cap_keywords[:3]):  # First 3 keywords are usually most specific
            if any(kw in keywords for kw in cap_keywords):
                score += 1.5  # Boost for agent name matching context
                if capability not in matched_caps:
                    matched_caps.append(capability)

    # Check work item type for natural matches
    if work_item.item_type == WorkItemType.TASK:
        if "engineering" in agent_caps or "engineer" in agent_name_lower:
            score += 1.0
    elif work_item.item_type == WorkItemType.BUG:
        if "engineering" in agent_caps or "engineer" in agent_name_lower:
            score += 1.0
    elif work_item.item_type == WorkItemType.STORY:
        if "product" in agent_caps or "product" in agent_name_lower:
            score += 0.5
    elif work_item.item_type == WorkItemType.EPIC:
        if "architecture" in agent_caps or "architect" in agent_name_lower:
            score += 0.5

    reason = f"matched capabilities: {', '.join(matched_caps)}" if matched_caps else "no matching capabilities"
    return score, reason


def find_best_agent_for_work_item(
    agents: List[Agent],
    work_item: WorkItem,
    min_score: float = 1.0,
) -> Optional[Tuple[Agent, float, str]]:
    """
    Find the best matching agent for a work item.

    Args:
        agents: List of project agents to consider
        work_item: The work item to assign
        min_score: Minimum score required for a match

    Returns:
        Tuple of (best_agent, score, reason) or None if no suitable agent found
    """
    if not agents:
        return None

    scored_agents = []
    for agent in agents:
        score, reason = _score_agent_for_work_item(agent, work_item)
        if score >= min_score:
            scored_agents.append((agent, score, reason))

    if not scored_agents:
        return None

    # Sort by score descending
    scored_agents.sort(key=lambda x: x[1], reverse=True)
    return scored_agents[0]


def auto_assign_work_item(
    board_service: BoardService,
    work_item: WorkItem,
    project_agents: List[Agent],
    project_owner_id: Optional[str] = None,
    actor: Optional[Actor] = None,
    org_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Automatically assign a work item to the most relevant agent or project owner.

    Args:
        board_service: BoardService instance
        work_item: The work item to assign
        project_agents: List of agents assigned to the project
        project_owner_id: Fallback user ID if no suitable agent found
        actor: Actor performing the assignment
        org_id: Organization ID for the operation

    Returns:
        Tuple of (success, message)
    """
    if actor is None:
        actor = Actor(id="system", role="system", surface="auto-assign")

    # Try to find a matching agent
    match = find_best_agent_for_work_item(project_agents, work_item)

    if match:
        agent, score, reason = match
        try:
            request = AssignWorkItemRequest(
                assignee_id=agent.id,
                assignee_type=AssigneeType.AGENT,
                reason=f"Auto-assigned: {reason} (score: {score:.1f})",
            )
            board_service.assign_work_item(work_item.item_id, request, actor, org_id=org_id)
            logger.info(f"Auto-assigned work item {work_item.item_id} to agent {agent.name} ({reason})")
            return True, f"Assigned to agent '{agent.name}' ({reason})"
        except Exception as e:
            logger.warning(f"Failed to auto-assign to agent {agent.id}: {e}")

    # Fallback to project owner
    if project_owner_id:
        try:
            request = AssignWorkItemRequest(
                assignee_id=project_owner_id,
                assignee_type=AssigneeType.USER,
                reason="Auto-assigned: No matching agent found, assigned to project owner",
            )
            board_service.assign_work_item(work_item.item_id, request, actor, org_id=org_id)
            logger.info(f"Auto-assigned work item {work_item.item_id} to project owner {project_owner_id}")
            return True, f"Assigned to project owner (no matching agent found)"
        except Exception as e:
            logger.warning(f"Failed to auto-assign to project owner: {e}")
            return False, f"Failed to assign: {e}"

    return False, "No suitable agent found and no project owner specified"
