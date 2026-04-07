#!/usr/bin/env python3
"""
Generate evaluation benchmark dataset from AGENTS.md behaviors.

This script extracts all behaviors from AGENTS.md and generates
a JSONL benchmark dataset for Midnighter evaluation pipelines.

Usage:
    python scripts/generate_benchmark.py --agents-md ../../AGENTS.md --output benchmarks/
"""

import argparse
import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import List, Optional


@dataclass
class BehaviorEntry:
    """Parsed behavior from AGENTS.md."""
    name: str
    when: str
    steps: List[str]
    role: Optional[str] = None


@dataclass
class BenchmarkCase:
    """A single benchmark evaluation case."""
    id: str
    behavior_name: str
    prompt: str
    expected_behavior: str
    expected_steps: List[str]
    category: str
    difficulty: str  # easy, medium, hard


def parse_behaviors_from_agents_md(content: str) -> List[BehaviorEntry]:
    """Extract all behavior definitions from AGENTS.md content."""
    behaviors = []

    # Pattern to match behavior sections
    # Matches ### `behavior_xyz` followed by content until next ### or ---
    pattern = r'### `(behavior_[a-z_]+)`\s*\n(.*?)(?=\n### `behavior_|---|\Z)'

    matches = re.findall(pattern, content, re.DOTALL)

    for name, body in matches:
        # Extract "When" section
        when_match = re.search(r'\*\*When\*\*:\s*(.+?)(?:\n-\s*\*\*Steps\*\*|\n\*\*Steps\*\*|\n-\s*\*\*Role\*\*)', body, re.DOTALL)
        when = when_match.group(1).strip() if when_match else ""

        # Extract Role if present
        role_match = re.search(r'\*\*Role\*\*:\s*(.+?)(?:\n-\s*\*\*|\n\*\*)', body, re.DOTALL)
        role = role_match.group(1).strip() if role_match else None

        # Extract Steps
        steps = []
        steps_section_match = re.search(r'\*\*Steps\*\*:\s*\n((?:\s+\d+\..+\n?)+)', body)
        if steps_section_match:
            steps_text = steps_section_match.group(1)
            step_matches = re.findall(r'\d+\.\s*\*\*([^*]+)\*\*:?\s*(.+?)(?=\n\s*\d+\.|\Z)', steps_text, re.DOTALL)
            for step_title, step_detail in step_matches:
                steps.append(f"{step_title.strip()}: {step_detail.strip()}")

        if not steps:
            # Fallback: try simpler pattern
            step_matches = re.findall(r'\d+\.\s+(.+?)(?=\n\s*\d+\.|\n\n|\Z)', body)
            steps = [s.strip() for s in step_matches if s.strip()]

        behaviors.append(BehaviorEntry(
            name=name,
            when=when,
            steps=steps,
            role=role
        ))

    return behaviors


def generate_prompts_for_behavior(behavior: BehaviorEntry) -> List[BenchmarkCase]:
    """Generate multiple benchmark cases for a single behavior."""
    cases = []

    # Prompt templates for different scenarios
    templates = [
        {
            "template": "I need to {when_simplified}. What should I do?",
            "category": "direct_query",
            "difficulty": "easy"
        },
        {
            "template": "Help me with {when_simplified}.",
            "category": "help_request",
            "difficulty": "easy"
        },
        {
            "template": "What's the best practice for {when_simplified}?",
            "category": "best_practice",
            "difficulty": "medium"
        },
        {
            "template": "I'm working on a task that involves {when_simplified}. Guide me through the process.",
            "category": "guided_workflow",
            "difficulty": "medium"
        },
        {
            "template": "We have a recurring issue with {when_simplified}. How should we standardize our approach?",
            "category": "standardization",
            "difficulty": "hard"
        }
    ]

    # Simplify the "when" clause for prompts
    when_simplified = behavior.when.lower()
    when_simplified = re.sub(r'\*\*', '', when_simplified)  # Remove markdown bold
    when_simplified = re.sub(r'\s+', ' ', when_simplified)  # Normalize whitespace
    when_simplified = when_simplified[:200]  # Truncate if too long

    for i, template_info in enumerate(templates):
        try:
            prompt = template_info["template"].format(when_simplified=when_simplified)
        except (KeyError, IndexError):
            prompt = template_info["template"].replace("{when_simplified}", when_simplified)

        case = BenchmarkCase(
            id=f"{behavior.name}_{i+1}",
            behavior_name=behavior.name,
            prompt=prompt,
            expected_behavior=behavior.name,
            expected_steps=behavior.steps,
            category=template_info["category"],
            difficulty=template_info["difficulty"]
        )
        cases.append(case)

    return cases


def generate_cross_behavior_cases(behaviors: List[BehaviorEntry]) -> List[BenchmarkCase]:
    """Generate cases that test behavior selection from multiple options."""
    cases = []

    # Group behaviors by related keywords
    keyword_groups = {
        "logging": ["behavior_use_raze_for_logging", "behavior_instrument_metrics_pipeline"],
        "security": ["behavior_prevent_secret_leaks", "behavior_rotate_leaked_credentials", "behavior_lock_down_security_surface"],
        "documentation": ["behavior_update_docs_after_changes", "behavior_curate_behavior_handbook"],
        "deployment": ["behavior_orchestrate_cicd", "behavior_use_breakeramp_for_environments"],
        "code_quality": ["behavior_extract_standalone_package", "behavior_align_storage_layers"],
    }

    behavior_map = {b.name: b for b in behaviors}

    for group_name, behavior_names in keyword_groups.items():
        existing = [name for name in behavior_names if name in behavior_map]
        if len(existing) >= 2:
            # Create a disambiguation case
            primary = behavior_map[existing[0]]
            cases.append(BenchmarkCase(
                id=f"cross_{group_name}_1",
                behavior_name=primary.name,
                prompt=f"I need help with {group_name.replace('_', ' ')}. Specifically, {primary.when[:100]}",
                expected_behavior=primary.name,
                expected_steps=primary.steps,
                category="cross_behavior_selection",
                difficulty="hard"
            ))

    return cases


def generate_negative_cases() -> List[BenchmarkCase]:
    """Generate cases where no behavior should match (tests hallucination resistance)."""
    return [
        BenchmarkCase(
            id="negative_1",
            behavior_name="NONE",
            prompt="What's the weather like today?",
            expected_behavior="NONE",
            expected_steps=[],
            category="negative",
            difficulty="easy"
        ),
        BenchmarkCase(
            id="negative_2",
            behavior_name="NONE",
            prompt="Tell me a joke about programming.",
            expected_behavior="NONE",
            expected_steps=[],
            category="negative",
            difficulty="easy"
        ),
        BenchmarkCase(
            id="negative_3",
            behavior_name="NONE",
            prompt="What is the capital of France?",
            expected_behavior="NONE",
            expected_steps=[],
            category="negative",
            difficulty="easy"
        ),
    ]


def write_benchmark(cases: List[BenchmarkCase], output_path: Path) -> None:
    """Write benchmark cases to JSONL file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for case in cases:
            f.write(json.dumps(asdict(case)) + '\n')

    print(f"✅ Wrote {len(cases)} benchmark cases to {output_path}")


def write_summary(behaviors: List[BehaviorEntry], cases: List[BenchmarkCase], output_path: Path) -> None:
    """Write a summary of the benchmark dataset."""
    summary = {
        "total_behaviors": len(behaviors),
        "total_cases": len(cases),
        "by_category": {},
        "by_difficulty": {},
        "behaviors": [b.name for b in behaviors]
    }

    for case in cases:
        summary["by_category"][case.category] = summary["by_category"].get(case.category, 0) + 1
        summary["by_difficulty"][case.difficulty] = summary["by_difficulty"].get(case.difficulty, 0) + 1

    with open(output_path, 'w') as f:
        json.dump(summary, f, indent=2)

    print(f"📊 Summary written to {output_path}")
    print(f"   Behaviors: {len(behaviors)}")
    print(f"   Total cases: {len(cases)}")
    print(f"   By difficulty: {summary['by_difficulty']}")


def main():
    parser = argparse.ArgumentParser(description="Generate Midnighter evaluation benchmark from AGENTS.md")
    parser.add_argument(
        "--agents-md",
        type=Path,
        default=Path(__file__).parent.parent.parent.parent / "AGENTS.md",
        help="Path to AGENTS.md file"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent.parent / "benchmarks",
        help="Output directory for benchmark files"
    )
    args = parser.parse_args()

    # Read AGENTS.md
    print(f"📖 Reading behaviors from {args.agents_md}")
    content = args.agents_md.read_text()

    # Parse behaviors
    behaviors = parse_behaviors_from_agents_md(content)
    print(f"   Found {len(behaviors)} behaviors")

    # Generate benchmark cases
    all_cases = []

    for behavior in behaviors:
        cases = generate_prompts_for_behavior(behavior)
        all_cases.extend(cases)

    # Add cross-behavior and negative cases
    all_cases.extend(generate_cross_behavior_cases(behaviors))
    all_cases.extend(generate_negative_cases())

    # Write outputs
    args.output.mkdir(parents=True, exist_ok=True)

    write_benchmark(all_cases, args.output / "evaluation_benchmark.jsonl")
    write_summary(behaviors, all_cases, args.output / "benchmark_summary.json")

    # Also write behaviors as JSON for reference
    behaviors_data = [asdict(b) for b in behaviors]
    with open(args.output / "behaviors.json", 'w') as f:
        json.dump(behaviors_data, f, indent=2)
    print(f"📝 Behaviors reference written to {args.output / 'behaviors.json'}")


if __name__ == "__main__":
    main()
