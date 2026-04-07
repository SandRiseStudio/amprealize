#!/usr/bin/env python3
"""
Test BCI with manually-provided behaviors (no database required).

This script demonstrates BCI working with real behaviors parsed from AGENTS.md
without needing PostgreSQL or other infrastructure.
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from amprealize.llm import (
    LLMClient,
    LLMConfig,
)
from amprealize.bci_contracts import (
    BehaviorMatch,
    RetrieveRequest,
    RetrieveResponse,
    RetrievalStrategy,
)


@dataclass
class ParsedBehavior:
    """A behavior parsed from AGENTS.md."""
    name: str
    description: str
    instruction: str
    trigger_keywords: List[str] = field(default_factory=list)
    role_focus: str = "STUDENT"
    tags: List[str] = field(default_factory=list)


def parse_behaviors_from_agents_md() -> List[ParsedBehavior]:
    """Parse behaviors from AGENTS.md."""
    agents_md_path = Path(__file__).parent.parent / "AGENTS.md"
    content = agents_md_path.read_text()

    behaviors = []
    behavior_pattern = re.compile(
        r'### `(behavior_[a-zA-Z0-9_]+)`\s*\n'
        r'- \*\*When\*\*:\s*(.+?)\n'
        r'- \*\*Steps\*\*:\s*\n((?:\s+\d+\..+\n)+)',
        re.MULTILINE
    )

    for match in behavior_pattern.finditer(content):
        name = match.group(1)
        when_clause = match.group(2).strip()
        steps_raw = match.group(3)

        # Parse steps
        steps = []
        for step_match in re.finditer(r'\d+\.\s+\*\*(.+?)\*\*:\s*(.+)', steps_raw):
            step_title = step_match.group(1)
            step_detail = step_match.group(2).strip()
            steps.append(f"{step_title}: {step_detail}")

        instruction = "\n".join(steps) if steps else when_clause

        # Extract keywords from when clause
        keywords = []
        keyword_terms = re.findall(r'(?:working with|touching|modifying|implementing|designing)\s+([^,\.]+)', when_clause.lower())
        for term in keyword_terms:
            keywords.extend(term.split())

        # Add behavior name parts as keywords
        name_parts = name.replace("behavior_", "").split("_")
        keywords.extend(name_parts)

        # Determine role from Quick Triggers table
        role = "STUDENT"  # default
        if "extract" in name or "standalone" in name:
            role = "TEACHER"
        elif "curate" in name or "handbook" in name:
            role = "STRATEGIST"

        behaviors.append(ParsedBehavior(
            name=name,
            description=when_clause,
            instruction=instruction,
            trigger_keywords=list(set(keywords))[:10],
            role_focus=role,
            tags=name_parts[:5],
        ))

    return behaviors


class InMemoryBehaviorRetriever:
    """Simple in-memory behavior retriever for testing."""

    def __init__(self, behaviors: List[ParsedBehavior]):
        self.behaviors = behaviors
        self.mode = "in-memory"

    def retrieve(self, request: RetrieveRequest) -> List[BehaviorMatch]:
        """Retrieve matching behaviors using simple keyword matching."""
        query_lower = (request.query or "").lower()
        query_words = set(query_lower.split())

        scored_behaviors = []
        for i, behavior in enumerate(self.behaviors):
            # Score based on keyword overlap
            behavior_words = set(behavior.trigger_keywords)
            behavior_words.update(behavior.name.lower().split("_"))
            behavior_words.update(behavior.description.lower().split())

            overlap = len(query_words & behavior_words)
            if overlap > 0 or any(kw in query_lower for kw in behavior.trigger_keywords):
                score = overlap / max(len(query_words), 1)
                # Boost if behavior name contains query words
                if any(word in behavior.name.lower() for word in query_words):
                    score += 0.5
                scored_behaviors.append((score, i, behavior))

        # Sort by score descending
        scored_behaviors.sort(key=lambda x: -x[0])

        # Return top_k matches
        matches = []
        for score, idx, behavior in scored_behaviors[:request.top_k]:
            match = BehaviorMatch(
                behavior_id=f"mem-{idx}",
                name=behavior.name,
                version="1.0.0",
                instruction=behavior.instruction[:500],
                description=behavior.description,
                score=min(score, 1.0),
            )
            matches.append(match)

        return matches


def compose_bci_prompt(behaviors: List[BehaviorMatch], user_query: str) -> str:
    """Compose a BCI-style prompt with prepended behaviors."""
    if not behaviors:
        return user_query

    behavior_section = "## Relevant Behaviors\n\n"
    behavior_section += "When solving the task below, reference these behaviors by name when you apply them.\n\n"

    for match in behaviors:
        behavior_section += f"### {match.name}\n"
        behavior_section += f"**When to use**: {match.description or 'N/A'}\n"
        if match.instruction:
            behavior_section += f"**Steps**:\n{match.instruction}\n"
        behavior_section += "\n"

    return f"{behavior_section}\n---\n\n## Task\n\n{user_query}"


def main():
    print("=" * 60)
    print("    BCI Test with In-Memory Behaviors")
    print("=" * 60)
    print()

    # Parse behaviors from AGENTS.md
    print("📖 Parsing behaviors from AGENTS.md...")
    behaviors = parse_behaviors_from_agents_md()
    print(f"   Found {len(behaviors)} behaviors")
    print()

    # Create in-memory retriever
    retriever = InMemoryBehaviorRetriever(behaviors)

    # Test query
    test_query = "How should I add logging to a new service?"

    print(f"🔍 Query: {test_query}")
    print()

    # Retrieve relevant behaviors
    request = RetrieveRequest(
        query=test_query,
        top_k=3,
        strategy=RetrievalStrategy.KEYWORD,
    )
    matches = retriever.retrieve(request)

    print(f"📚 Retrieved {len(matches)} behaviors:")
    for match in matches:
        print(f"   • {match.name} (score: {match.score:.2f})")
        desc = match.description or "No description"
        print(f"     {desc[:80]}...")
    print()

    # Compose BCI prompt
    bci_prompt = compose_bci_prompt(matches, test_query)

    # Get LLM provider
    print("🤖 Generating response with LLM...")
    print()

    config = LLMConfig.from_env()
    client = LLMClient(config)

    # Create request with BCI prompt
    messages = [
        {"role": "system", "content": "You are a helpful assistant that follows the behavior guidelines provided."},
        {"role": "user", "content": bci_prompt},
    ]

    response = client.call(messages, max_tokens=500, temperature=0.7)

    print("=" * 60)
    print("    Response")
    print("=" * 60)
    print()
    print(response.content)
    print()
    print("-" * 60)
    print(f"📊 Stats:")
    print(f"   Model: {response.model}")
    print(f"   Behaviors used: {len(matches)}")
    print(f"   Input tokens: {response.input_tokens}")
    print(f"   Output tokens: {response.output_tokens}")
    print(f"   Cost: ${response.estimated_cost_usd:.6f}" if response.estimated_cost_usd else "   Cost: N/A")
    print()

    # Check if behaviors were cited
    cited = [m.name for m in matches if m.name in response.content]
    if cited:
        print(f"✅ Behaviors cited in response: {', '.join(cited)}")
    else:
        print("⚠️  No behaviors explicitly cited in response")


if __name__ == "__main__":
    main()
