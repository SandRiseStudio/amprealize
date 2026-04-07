"""Synthetic test corpus for BC-SFT benchmark validation.

This corpus provides reproducible test cases for validating:
1. Token savings (46% target per Metacognitive Reuse paper)
2. Retrieval latency (250ms P95 target)
3. Behavior coverage across domains

Usage:
    from tests.benchmarks.synthetic_corpus import BENCHMARK_CORPUS, expand_corpus

    # Get base corpus
    for test_case in BENCHMARK_CORPUS:
        query = test_case["query"]
        expected = test_case["expected_behaviors"]

    # Get expanded corpus for stress testing
    expanded = expand_corpus(BENCHMARK_CORPUS, multiplier=10)
"""

from __future__ import annotations

import random
from typing import Any, Dict, List


# Base synthetic test corpus covering all behavior domains
BENCHMARK_CORPUS: List[Dict[str, Any]] = [
    # =====================================================================
    # LOGGING DOMAIN (behavior_use_raze_for_logging)
    # =====================================================================
    {
        "query": "How do I add structured logging to my service?",
        "expected_behaviors": ["behavior_use_raze_for_logging"],
        "domain": "logging",
        "complexity": "medium",
        "expected_token_baseline": 180,
        "expected_token_bci": 95,
    },
    {
        "query": "What's the best way to log API requests with context?",
        "expected_behaviors": ["behavior_use_raze_for_logging"],
        "domain": "logging",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },
    {
        "query": "Configure logging for my FastAPI endpoint",
        "expected_behaviors": ["behavior_use_raze_for_logging"],
        "domain": "logging",
        "complexity": "easy",
        "expected_token_baseline": 150,
        "expected_token_bci": 80,
    },
    {
        "query": "How do I include run_id in all log messages?",
        "expected_behaviors": ["behavior_use_raze_for_logging"],
        "domain": "logging",
        "complexity": "easy",
        "expected_token_baseline": 140,
        "expected_token_bci": 75,
    },

    # =====================================================================
    # OBSERVABILITY DOMAIN (behavior_instrument_metrics_pipeline)
    # =====================================================================
    {
        "query": "I need to add telemetry to track user actions",
        "expected_behaviors": ["behavior_use_raze_for_logging", "behavior_instrument_metrics_pipeline"],
        "domain": "observability",
        "complexity": "medium",
        "expected_token_baseline": 250,
        "expected_token_bci": 120,
    },
    {
        "query": "How do I emit custom metrics to the dashboard?",
        "expected_behaviors": ["behavior_instrument_metrics_pipeline"],
        "domain": "observability",
        "complexity": "medium",
        "expected_token_baseline": 220,
        "expected_token_bci": 115,
    },
    {
        "query": "Set up Kafka telemetry events for my service",
        "expected_behaviors": ["behavior_instrument_metrics_pipeline"],
        "domain": "observability",
        "complexity": "hard",
        "expected_token_baseline": 300,
        "expected_token_bci": 150,
    },

    # =====================================================================
    # ENVIRONMENT MANAGEMENT (behavior_use_breakeramp_for_environments)
    # =====================================================================
    {
        "query": "How do I set up a development container environment?",
        "expected_behaviors": ["behavior_use_breakeramp_for_environments"],
        "domain": "environments",
        "complexity": "medium",
        "expected_token_baseline": 230,
        "expected_token_bci": 120,
    },
    {
        "query": "Create a blueprint for my test infrastructure",
        "expected_behaviors": ["behavior_use_breakeramp_for_environments"],
        "domain": "environments",
        "complexity": "medium",
        "expected_token_baseline": 210,
        "expected_token_bci": 110,
    },
    {
        "query": "Use podman to run my service locally",
        "expected_behaviors": ["behavior_use_breakeramp_for_environments"],
        "domain": "environments",
        "complexity": "easy",
        "expected_token_baseline": 180,
        "expected_token_bci": 95,
    },
    {
        "query": "Configure breakeramp with compliance hooks",
        "expected_behaviors": ["behavior_use_breakeramp_for_environments"],
        "domain": "environments",
        "complexity": "hard",
        "expected_token_baseline": 280,
        "expected_token_bci": 140,
    },

    # =====================================================================
    # SECURITY DOMAIN (behavior_prevent_secret_leaks, behavior_rotate_leaked_credentials)
    # =====================================================================
    {
        "query": "I accidentally committed an API key to git",
        "expected_behaviors": ["behavior_rotate_leaked_credentials", "behavior_prevent_secret_leaks"],
        "domain": "security",
        "complexity": "urgent",
        "expected_token_baseline": 350,
        "expected_token_bci": 160,
    },
    {
        "query": "How do I add auth to my endpoint?",
        "expected_behaviors": ["behavior_lock_down_security_surface"],
        "domain": "security",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },
    {
        "query": "What pre-commit hooks should I use for secrets?",
        "expected_behaviors": ["behavior_prevent_secret_leaks"],
        "domain": "security",
        "complexity": "easy",
        "expected_token_baseline": 160,
        "expected_token_bci": 85,
    },
    {
        "query": "Configure CORS for my API",
        "expected_behaviors": ["behavior_lock_down_security_surface"],
        "domain": "security",
        "complexity": "medium",
        "expected_token_baseline": 190,
        "expected_token_bci": 100,
    },
    {
        "query": "Set up bearer token authentication",
        "expected_behaviors": ["behavior_lock_down_security_surface"],
        "domain": "security",
        "complexity": "medium",
        "expected_token_baseline": 220,
        "expected_token_bci": 115,
    },

    # =====================================================================
    # MCP TOOLING (behavior_prefer_mcp_tools)
    # =====================================================================
    {
        "query": "Should I use CLI commands or MCP tools?",
        "expected_behaviors": ["behavior_prefer_mcp_tools"],
        "domain": "tooling",
        "complexity": "easy",
        "expected_token_baseline": 180,
        "expected_token_bci": 95,
    },
    {
        "query": "How do I expose my function as an MCP tool?",
        "expected_behaviors": ["behavior_prefer_mcp_tools"],
        "domain": "tooling",
        "complexity": "medium",
        "expected_token_baseline": 240,
        "expected_token_bci": 125,
    },
    {
        "query": "Which MCP server tools are available?",
        "expected_behaviors": ["behavior_prefer_mcp_tools"],
        "domain": "tooling",
        "complexity": "easy",
        "expected_token_baseline": 150,
        "expected_token_bci": 80,
    },

    # =====================================================================
    # DOCUMENTATION (behavior_update_docs_after_changes)
    # =====================================================================
    {
        "query": "When should I update the README?",
        "expected_behaviors": ["behavior_update_docs_after_changes"],
        "domain": "documentation",
        "complexity": "easy",
        "expected_token_baseline": 140,
        "expected_token_bci": 75,
    },
    {
        "query": "I changed the API, what docs need updating?",
        "expected_behaviors": ["behavior_update_docs_after_changes"],
        "domain": "documentation",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },
    {
        "query": "Update BUILD_TIMELINE.md after my changes",
        "expected_behaviors": ["behavior_update_docs_after_changes"],
        "domain": "documentation",
        "complexity": "easy",
        "expected_token_baseline": 130,
        "expected_token_bci": 70,
    },

    # =====================================================================
    # CI/CD (behavior_orchestrate_cicd, behavior_git_governance)
    # =====================================================================
    {
        "query": "How do I set up the CI pipeline?",
        "expected_behaviors": ["behavior_orchestrate_cicd"],
        "domain": "cicd",
        "complexity": "medium",
        "expected_token_baseline": 260,
        "expected_token_bci": 135,
    },
    {
        "query": "What should my deployment workflow include?",
        "expected_behaviors": ["behavior_orchestrate_cicd", "behavior_git_governance"],
        "domain": "cicd",
        "complexity": "hard",
        "expected_token_baseline": 320,
        "expected_token_bci": 155,
    },
    {
        "query": "Configure rollback for failed deployments",
        "expected_behaviors": ["behavior_orchestrate_cicd"],
        "domain": "cicd",
        "complexity": "hard",
        "expected_token_baseline": 280,
        "expected_token_bci": 140,
    },
    {
        "query": "What branching strategy should I use?",
        "expected_behaviors": ["behavior_git_governance"],
        "domain": "cicd",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },
    {
        "query": "Set up merge policy for PRs",
        "expected_behaviors": ["behavior_git_governance"],
        "domain": "cicd",
        "complexity": "medium",
        "expected_token_baseline": 190,
        "expected_token_bci": 100,
    },

    # =====================================================================
    # ARCHITECTURE (behavior_extract_standalone_package)
    # =====================================================================
    {
        "query": "Should I extract this code into a separate package?",
        "expected_behaviors": ["behavior_extract_standalone_package"],
        "domain": "architecture",
        "complexity": "medium",
        "expected_token_baseline": 240,
        "expected_token_bci": 125,
    },
    {
        "query": "How do I structure a reusable service?",
        "expected_behaviors": ["behavior_extract_standalone_package"],
        "domain": "architecture",
        "complexity": "hard",
        "expected_token_baseline": 300,
        "expected_token_bci": 150,
    },
    {
        "query": "Create a standalone package following the Raze pattern",
        "expected_behaviors": ["behavior_extract_standalone_package"],
        "domain": "architecture",
        "complexity": "hard",
        "expected_token_baseline": 280,
        "expected_token_bci": 140,
    },

    # =====================================================================
    # BEHAVIOR CURATION (behavior_curate_behavior_handbook)
    # =====================================================================
    {
        "query": "I've seen this pattern 3 times, should I create a behavior?",
        "expected_behaviors": ["behavior_curate_behavior_handbook"],
        "domain": "meta",
        "complexity": "medium",
        "expected_token_baseline": 220,
        "expected_token_bci": 115,
    },
    {
        "query": "How do I propose a new behavior?",
        "expected_behaviors": ["behavior_curate_behavior_handbook"],
        "domain": "meta",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },
    {
        "query": "What's the behavior lifecycle?",
        "expected_behaviors": ["behavior_curate_behavior_handbook"],
        "domain": "meta",
        "complexity": "easy",
        "expected_token_baseline": 180,
        "expected_token_bci": 95,
    },

    # =====================================================================
    # CONFIGURATION (behavior_externalize_configuration)
    # =====================================================================
    {
        "query": "I have a hardcoded file path in my code",
        "expected_behaviors": ["behavior_externalize_configuration"],
        "domain": "configuration",
        "complexity": "easy",
        "expected_token_baseline": 160,
        "expected_token_bci": 85,
    },
    {
        "query": "Where should secrets come from?",
        "expected_behaviors": ["behavior_externalize_configuration", "behavior_prevent_secret_leaks"],
        "domain": "configuration",
        "complexity": "medium",
        "expected_token_baseline": 220,
        "expected_token_bci": 110,
    },
    {
        "query": "Configure environment variables for production",
        "expected_behaviors": ["behavior_externalize_configuration"],
        "domain": "configuration",
        "complexity": "medium",
        "expected_token_baseline": 200,
        "expected_token_bci": 105,
    },

    # =====================================================================
    # STORAGE (behavior_align_storage_layers)
    # =====================================================================
    {
        "query": "How do I add a new storage adapter?",
        "expected_behaviors": ["behavior_align_storage_layers"],
        "domain": "storage",
        "complexity": "hard",
        "expected_token_baseline": 280,
        "expected_token_bci": 140,
    },
    {
        "query": "Configure audit log storage",
        "expected_behaviors": ["behavior_align_storage_layers"],
        "domain": "storage",
        "complexity": "medium",
        "expected_token_baseline": 220,
        "expected_token_bci": 115,
    },

    # =====================================================================
    # EXECUTION RECORDS (behavior_unify_execution_records)
    # =====================================================================
    {
        "query": "How do I track run status across surfaces?",
        "expected_behaviors": ["behavior_unify_execution_records"],
        "domain": "execution",
        "complexity": "hard",
        "expected_token_baseline": 260,
        "expected_token_bci": 130,
    },
    {
        "query": "Implement SSE for run progress",
        "expected_behaviors": ["behavior_unify_execution_records"],
        "domain": "execution",
        "complexity": "hard",
        "expected_token_baseline": 300,
        "expected_token_bci": 150,
    },
]


def expand_corpus(
    base_corpus: List[Dict[str, Any]],
    multiplier: int = 10,
    add_variations: bool = True,
) -> List[Dict[str, Any]]:
    """Expand corpus for stress testing.

    Args:
        base_corpus: Base test corpus to expand
        multiplier: Number of times to repeat base corpus
        add_variations: If True, add query variations

    Returns:
        Expanded corpus with variations
    """
    expanded = []

    # Query variation templates
    variations = [
        "How do I {action}?",
        "What's the best way to {action}?",
        "I need to {action}",
        "Can you help me {action}?",
        "Explain how to {action}",
        "Show me how to {action}",
        "Steps for {action}",
        "{action} - how?",
    ]

    for _ in range(multiplier):
        for case in base_corpus:
            expanded.append(case.copy())

            if add_variations:
                # Extract action from query
                query = case["query"].lower()

                # Simple action extraction
                for prefix in ["how do i ", "what's the best way to ", "i need to "]:
                    if query.startswith(prefix):
                        action = query[len(prefix):].rstrip("?")

                        # Create variation
                        variation = random.choice(variations)
                        varied_case = case.copy()
                        varied_case["query"] = variation.format(action=action)
                        varied_case["is_variation"] = True
                        expanded.append(varied_case)
                        break

    return expanded


def get_corpus_stats(corpus: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Get statistics about a test corpus.

    Returns:
        Dict with corpus statistics
    """
    domains = {}
    complexity_counts = {}
    behavior_counts = {}
    total_baseline_tokens = 0
    total_bci_tokens = 0

    for case in corpus:
        domain = case.get("domain", "unknown")
        domains[domain] = domains.get(domain, 0) + 1

        complexity = case.get("complexity", "unknown")
        complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1

        for behavior in case.get("expected_behaviors", []):
            behavior_counts[behavior] = behavior_counts.get(behavior, 0) + 1

        total_baseline_tokens += case.get("expected_token_baseline", 0)
        total_bci_tokens += case.get("expected_token_bci", 0)

    expected_savings = (
        ((total_baseline_tokens - total_bci_tokens) / total_baseline_tokens * 100)
        if total_baseline_tokens > 0 else 0
    )

    return {
        "total_cases": len(corpus),
        "domains": domains,
        "complexity_distribution": complexity_counts,
        "behavior_coverage": behavior_counts,
        "expected_token_savings_percent": expected_savings,
        "total_baseline_tokens": total_baseline_tokens,
        "total_bci_tokens": total_bci_tokens,
    }


if __name__ == "__main__":
    import json

    stats = get_corpus_stats(BENCHMARK_CORPUS)
    print("Benchmark Corpus Statistics:")
    print(json.dumps(stats, indent=2))

    print(f"\nExpected Token Savings: {stats['expected_token_savings_percent']:.1f}%")
