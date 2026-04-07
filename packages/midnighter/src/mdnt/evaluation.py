"""Evaluation service for fine-tuned models.

Provides automated evaluation pipelines for:
- Behavior adherence scoring
- Hallucination detection
- A/B model comparison
- Benchmark dataset management

Example:
    from mdnt import MidnighterService
    from mdnt.evaluation import EvaluationService

    eval_service = EvaluationService(midnighter=midnighter_service)

    # Run evaluation on a fine-tuned model
    result = await eval_service.evaluate_model(
        model_id="my-finetuned-model",
        benchmark="behavior_adherence",
    )

    # Compare two models
    comparison = await eval_service.compare_models(
        baseline_model="gpt-4o-mini",
        candidate_model="ft:gpt-4o-mini:my-org:my-model:abc123",
        test_behaviors=["behavior_code_review", "behavior_logging"],
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid

logger = logging.getLogger(__name__)

# Check for OpenAI availability
try:
    from openai import AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    AsyncOpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


class EvaluationMetric(str, Enum):
    """Evaluation metrics for fine-tuned models."""
    BEHAVIOR_ADHERENCE = "behavior_adherence"
    CITATION_ACCURACY = "citation_accuracy"
    HALLUCINATION_RATE = "hallucination_rate"
    RESPONSE_QUALITY = "response_quality"
    LATENCY_P50 = "latency_p50"
    LATENCY_P99 = "latency_p99"
    TOKEN_EFFICIENCY = "token_efficiency"


class InjectionStrategy(str, Enum):
    """Prompt injection strategies for BCI comparison."""
    BASELINE = "baseline"         # No BCI, no pack, no overlay
    BCI_ONLY = "bci_only"         # Behavior retrieval without knowledge pack
    PACK_BCI = "pack_bci"         # Full pack activation + BCI + overlay


@dataclass
class BenchmarkExample:
    """Single example in an evaluation benchmark."""
    example_id: str
    prompt: str
    expected_behaviors: List[str]
    context: Optional[str] = None
    expected_response_contains: Optional[List[str]] = None
    expected_response_excludes: Optional[List[str]] = None
    difficulty: str = "medium"  # easy, medium, hard
    category: str = "general"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "example_id": self.example_id,
            "prompt": self.prompt,
            "expected_behaviors": self.expected_behaviors,
            "context": self.context,
            "expected_response_contains": self.expected_response_contains,
            "expected_response_excludes": self.expected_response_excludes,
            "difficulty": self.difficulty,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BenchmarkExample":
        return cls(
            example_id=data.get("example_id", str(uuid.uuid4())),
            prompt=data["prompt"],
            expected_behaviors=data["expected_behaviors"],
            context=data.get("context"),
            expected_response_contains=data.get("expected_response_contains"),
            expected_response_excludes=data.get("expected_response_excludes"),
            difficulty=data.get("difficulty", "medium"),
            category=data.get("category", "general"),
        )


@dataclass
class EvaluationResult:
    """Result of evaluating a model on a benchmark."""
    evaluation_id: str
    model_id: str
    benchmark_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_examples: int
    completed_examples: int
    metrics: Dict[str, float]
    example_results: List[Dict[str, Any]]
    errors: List[str]
    status: str = "running"  # running, completed, failed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "model_id": self.model_id,
            "benchmark_name": self.benchmark_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_examples": self.total_examples,
            "completed_examples": self.completed_examples,
            "metrics": self.metrics,
            "example_results": self.example_results,
            "errors": self.errors,
            "status": self.status,
        }


@dataclass
class ComparisonResult:
    """Result of comparing two models."""
    comparison_id: str
    baseline_model: str
    candidate_model: str
    benchmark_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_examples: int
    baseline_metrics: Dict[str, float]
    candidate_metrics: Dict[str, float]
    improvement: Dict[str, float]  # Positive = candidate better
    winner: str  # "baseline", "candidate", or "tie"
    confidence: float  # 0-1
    example_comparisons: List[Dict[str, Any]]
    status: str = "running"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "baseline_model": self.baseline_model,
            "candidate_model": self.candidate_model,
            "benchmark_name": self.benchmark_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_examples": self.total_examples,
            "baseline_metrics": self.baseline_metrics,
            "candidate_metrics": self.candidate_metrics,
            "improvement": self.improvement,
            "winner": self.winner,
            "confidence": self.confidence,
            "example_comparisons": self.example_comparisons,
            "status": self.status,
        }


@dataclass
class StrategyComparisonResult:
    """Result of comparing injection strategies on the same model and benchmark."""
    comparison_id: str
    model_id: str
    benchmark_name: str
    started_at: datetime
    completed_at: Optional[datetime]
    total_examples: int
    strategy_results: Dict[str, EvaluationResult]  # strategy -> result
    strategy_metrics: Dict[str, Dict[str, float]]   # strategy -> metrics
    improvements: Dict[str, Dict[str, float]]        # strategy -> improvement over baseline
    token_accounting: Dict[str, Dict[str, float]]    # strategy -> token stats
    winner: str   # best strategy name
    status: str = "running"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "model_id": self.model_id,
            "benchmark_name": self.benchmark_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_examples": self.total_examples,
            "strategy_metrics": self.strategy_metrics,
            "improvements": self.improvements,
            "token_accounting": self.token_accounting,
            "winner": self.winner,
            "status": self.status,
        }


@dataclass
class Benchmark:
    """Evaluation benchmark with test examples."""
    name: str
    description: str
    examples: List[BenchmarkExample]
    version: str = "1.0"
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "examples": [ex.to_dict() for ex in self.examples],
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Benchmark":
        examples = [BenchmarkExample.from_dict(ex) for ex in data.get("examples", [])]
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            examples=examples,
            version=data.get("version", "1.0"),
            created_at=created_at,
        )

    def save(self, path: str) -> None:
        """Save benchmark to JSON file."""
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> "Benchmark":
        """Load benchmark from JSON file."""
        with open(path) as f:
            return cls.from_dict(json.load(f))


class EvaluationService:
    """Service for evaluating fine-tuned models.

    Provides:
    - Behavior adherence evaluation
    - Hallucination detection
    - A/B model comparison
    - Benchmark management
    - Cost tracking for evaluations

    Example:
        eval_service = EvaluationService()

        # Evaluate a model
        result = await eval_service.evaluate_model(
            model_id="ft:gpt-4o-mini:my-org:mdnt-model:abc123",
            benchmark="behavior_adherence",
        )

        print(f"Behavior Adherence: {result.metrics['behavior_adherence']:.2%}")
        print(f"Hallucination Rate: {result.metrics['hallucination_rate']:.2%}")
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        on_metric: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        on_cost: Optional[Callable[[str, int, float], None]] = None,
        benchmarks_dir: str = "./benchmarks",
    ) -> None:
        """Initialize evaluation service.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var).
            on_metric: Callback for metrics (event_type, data).
            on_cost: Callback for cost tracking (job_id, tokens, cost_usd).
            benchmarks_dir: Directory for benchmark files.
        """
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._on_metric = on_metric
        self._on_cost = on_cost
        self._benchmarks_dir = benchmarks_dir

        # Cached benchmarks
        self._benchmarks: Dict[str, Benchmark] = {}

        # Pricing (as of 2024)
        self._pricing = {
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},  # per 1M tokens
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "ft:gpt-4o-mini": {"input": 0.30, "output": 1.20},  # Fine-tuned
            "ft:gpt-4o": {"input": 5.00, "output": 20.00},
        }

        # Create benchmarks directory
        os.makedirs(self._benchmarks_dir, exist_ok=True)

        logger.info("EvaluationService initialized (benchmarks_dir=%s)", benchmarks_dir)

    async def evaluate_model(
        self,
        model_id: str,
        benchmark: str | Benchmark,
        *,
        sample_size: Optional[int] = None,
        timeout_per_example: float = 30.0,
        temperature: float = 0.0,
    ) -> EvaluationResult:
        """Evaluate a model on a benchmark.

        Args:
            model_id: Model to evaluate (fine-tuned or base).
            benchmark: Benchmark name or Benchmark object.
            sample_size: Limit examples (None = all).
            timeout_per_example: Timeout per inference.
            temperature: Sampling temperature.

        Returns:
            EvaluationResult with metrics and per-example results.
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("openai package required: pip install midnighter[openai]")

        # Load benchmark
        if isinstance(benchmark, str):
            bench = self.get_benchmark(benchmark)
            if not bench:
                raise ValueError(f"Benchmark not found: {benchmark}")
        else:
            bench = benchmark

        # Select examples
        examples = bench.examples
        if sample_size and sample_size < len(examples):
            import random
            examples = random.sample(examples, sample_size)

        evaluation_id = str(uuid.uuid4())
        result = EvaluationResult(
            evaluation_id=evaluation_id,
            model_id=model_id,
            benchmark_name=bench.name,
            started_at=datetime.utcnow(),
            completed_at=None,
            total_examples=len(examples),
            completed_examples=0,
            metrics={},
            example_results=[],
            errors=[],
            status="running",
        )

        # Initialize OpenAI client
        client = AsyncOpenAI(api_key=self._api_key)

        # Track metrics
        total_tokens = 0
        behavior_adherence_scores: List[float] = []
        citation_accuracy_scores: List[float] = []
        hallucination_scores: List[float] = []
        latencies: List[float] = []

        # Evaluate each example
        for example in examples:
            try:
                start_time = asyncio.get_event_loop().time()

                # Build prompt
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "You are a helpful AI assistant that follows behavior-conditioned guidelines. "
                            "When applying behaviors, cite them in your response using the format: `behavior_name` (Role)."
                        ),
                    },
                ]
                if example.context:
                    messages.append({"role": "system", "content": f"Context: {example.context}"})
                messages.append({"role": "user", "content": example.prompt})

                # Get response
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=model_id,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=1000,
                    ),
                    timeout=timeout_per_example,
                )

                end_time = asyncio.get_event_loop().time()
                latency = end_time - start_time
                latencies.append(latency)

                # Extract response
                response_text = response.choices[0].message.content or ""
                tokens_used = response.usage.total_tokens if response.usage else 0
                total_tokens += tokens_used

                # Score response
                adherence = self._score_behavior_adherence(
                    response_text,
                    example.expected_behaviors,
                )
                behavior_adherence_scores.append(adherence)

                citation = self._score_citation_accuracy(
                    response_text,
                    example.expected_behaviors,
                )
                citation_accuracy_scores.append(citation)

                hallucination = self._detect_hallucinations(
                    response_text,
                    example.expected_behaviors,
                    example.expected_response_excludes,
                )
                hallucination_scores.append(hallucination)

                # Check expected content
                contains_expected = True
                if example.expected_response_contains:
                    for expected in example.expected_response_contains:
                        if expected.lower() not in response_text.lower():
                            contains_expected = False
                            break

                excludes_forbidden = True
                if example.expected_response_excludes:
                    for forbidden in example.expected_response_excludes:
                        if forbidden.lower() in response_text.lower():
                            excludes_forbidden = False
                            break

                result.example_results.append({
                    "example_id": example.example_id,
                    "prompt": example.prompt[:100] + "..." if len(example.prompt) > 100 else example.prompt,
                    "response": response_text[:200] + "..." if len(response_text) > 200 else response_text,
                    "expected_behaviors": example.expected_behaviors,
                    "behavior_adherence": adherence,
                    "citation_accuracy": citation,
                    "hallucination_score": hallucination,
                    "contains_expected": contains_expected,
                    "excludes_forbidden": excludes_forbidden,
                    "latency_seconds": latency,
                    "tokens": tokens_used,
                })

                result.completed_examples += 1

            except asyncio.TimeoutError:
                result.errors.append(f"Timeout on example {example.example_id}")
            except Exception as e:
                result.errors.append(f"Error on example {example.example_id}: {str(e)}")
                logger.exception("Error evaluating example %s", example.example_id)

        # Calculate aggregate metrics
        if behavior_adherence_scores:
            result.metrics[EvaluationMetric.BEHAVIOR_ADHERENCE.value] = (
                sum(behavior_adherence_scores) / len(behavior_adherence_scores)
            )
        if citation_accuracy_scores:
            result.metrics[EvaluationMetric.CITATION_ACCURACY.value] = (
                sum(citation_accuracy_scores) / len(citation_accuracy_scores)
            )
        if hallucination_scores:
            result.metrics[EvaluationMetric.HALLUCINATION_RATE.value] = (
                sum(hallucination_scores) / len(hallucination_scores)
            )
        if latencies:
            sorted_latencies = sorted(latencies)
            result.metrics[EvaluationMetric.LATENCY_P50.value] = (
                sorted_latencies[len(sorted_latencies) // 2]
            )
            result.metrics[EvaluationMetric.LATENCY_P99.value] = (
                sorted_latencies[int(len(sorted_latencies) * 0.99)]
            )

        result.metrics["total_tokens"] = total_tokens
        result.metrics["examples_evaluated"] = result.completed_examples

        # Calculate cost
        cost_usd = self._calculate_cost(model_id, total_tokens)
        result.metrics["cost_usd"] = cost_usd

        # Emit cost callback
        if self._on_cost:
            self._on_cost(evaluation_id, total_tokens, cost_usd)

        # Emit metric callback
        if self._on_metric:
            self._on_metric("evaluation_completed", {
                "evaluation_id": evaluation_id,
                "model_id": model_id,
                "benchmark": bench.name,
                "behavior_adherence": result.metrics.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0),
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
            })

        result.completed_at = datetime.utcnow()
        result.status = "completed" if not result.errors else "completed_with_errors"

        return result

    async def compare_models(
        self,
        baseline_model: str,
        candidate_model: str,
        benchmark: str | Benchmark,
        *,
        sample_size: Optional[int] = None,
    ) -> ComparisonResult:
        """Compare two models on the same benchmark.

        Args:
            baseline_model: Baseline model ID.
            candidate_model: Candidate model ID (usually fine-tuned).
            benchmark: Benchmark name or object.
            sample_size: Limit examples.

        Returns:
            ComparisonResult with improvement metrics.
        """
        comparison_id = str(uuid.uuid4())

        # Run evaluations in parallel
        baseline_result, candidate_result = await asyncio.gather(
            self.evaluate_model(baseline_model, benchmark, sample_size=sample_size),
            self.evaluate_model(candidate_model, benchmark, sample_size=sample_size),
        )

        # Calculate improvements
        improvement: Dict[str, float] = {}
        for metric in [
            EvaluationMetric.BEHAVIOR_ADHERENCE.value,
            EvaluationMetric.CITATION_ACCURACY.value,
        ]:
            baseline_val = baseline_result.metrics.get(metric, 0)
            candidate_val = candidate_result.metrics.get(metric, 0)
            if baseline_val > 0:
                improvement[metric] = (candidate_val - baseline_val) / baseline_val
            else:
                improvement[metric] = candidate_val

        # Hallucination: lower is better
        baseline_hall = baseline_result.metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
        candidate_hall = candidate_result.metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
        if baseline_hall > 0:
            improvement[EvaluationMetric.HALLUCINATION_RATE.value] = (baseline_hall - candidate_hall) / baseline_hall
        else:
            improvement[EvaluationMetric.HALLUCINATION_RATE.value] = -candidate_hall

        # Determine winner
        adherence_better = improvement.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0) > 0.05
        hallucination_better = improvement.get(EvaluationMetric.HALLUCINATION_RATE.value, 0) > 0.05

        if adherence_better and hallucination_better:
            winner = "candidate"
            confidence = 0.9
        elif adherence_better or hallucination_better:
            winner = "candidate"
            confidence = 0.7
        elif improvement.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0) < -0.05:
            winner = "baseline"
            confidence = 0.7
        else:
            winner = "tie"
            confidence = 0.5

        # Build example comparisons
        example_comparisons = []
        for base_ex, cand_ex in zip(baseline_result.example_results, candidate_result.example_results):
            example_comparisons.append({
                "example_id": base_ex.get("example_id"),
                "baseline_adherence": base_ex.get("behavior_adherence", 0),
                "candidate_adherence": cand_ex.get("behavior_adherence", 0),
                "baseline_response": base_ex.get("response", "")[:100],
                "candidate_response": cand_ex.get("response", "")[:100],
            })

        return ComparisonResult(
            comparison_id=comparison_id,
            baseline_model=baseline_model,
            candidate_model=candidate_model,
            benchmark_name=baseline_result.benchmark_name,
            started_at=baseline_result.started_at,
            completed_at=datetime.utcnow(),
            total_examples=baseline_result.total_examples,
            baseline_metrics=baseline_result.metrics,
            candidate_metrics=candidate_result.metrics,
            improvement=improvement,
            winner=winner,
            confidence=confidence,
            example_comparisons=example_comparisons,
            status="completed",
        )

    async def compare_injection_strategies(
        self,
        model_id: str,
        benchmark: str | Benchmark,
        strategies: Optional[List[InjectionStrategy]] = None,
        *,
        sample_size: Optional[int] = None,
        system_prompt_builder: Optional[Callable[[InjectionStrategy, BenchmarkExample], List[Dict[str, str]]]] = None,
    ) -> StrategyComparisonResult:
        """Compare BCI injection strategies on the same model and benchmark.

        Runs the same prompts with different injection strategies:
        - BASELINE: No BCI, no pack, no overlay
        - BCI_ONLY: Behavior retrieval without knowledge pack
        - PACK_BCI: Full pack activation + BCI + overlay

        Args:
            model_id: Model to evaluate across all strategies.
            benchmark: Benchmark name or Benchmark object.
            strategies: Strategies to compare (default: all three).
            sample_size: Limit examples (None = all).
            system_prompt_builder: Optional callback that builds system
                messages for a given strategy and example. Signature:
                (strategy, example) -> list of message dicts.
                If None, a default prompt is used per strategy.

        Returns:
            StrategyComparisonResult with per-strategy metrics and improvements.
        """
        if strategies is None:
            strategies = list(InjectionStrategy)

        comparison_id = str(uuid.uuid4())
        started_at = datetime.utcnow()

        # Load benchmark once
        if isinstance(benchmark, str):
            bench = self.get_benchmark(benchmark)
            if not bench:
                raise ValueError(f"Benchmark not found: {benchmark}")
        else:
            bench = benchmark

        # Select examples
        examples = bench.examples
        if sample_size and sample_size < len(examples):
            import random
            examples = random.sample(examples, sample_size)

        # Run evaluation for each strategy
        strategy_results: Dict[str, EvaluationResult] = {}
        for strategy in strategies:
            # Create a strategy-specific benchmark with modified prompts
            strategy_bench = self._build_strategy_benchmark(
                bench, examples, strategy, system_prompt_builder
            )
            result = await self.evaluate_model(
                model_id, strategy_bench, sample_size=None
            )
            strategy_results[strategy.value] = result

        # Collect per-strategy metrics
        strategy_metrics: Dict[str, Dict[str, float]] = {}
        for s_name, s_result in strategy_results.items():
            strategy_metrics[s_name] = dict(s_result.metrics)

        # Compute improvements over baseline
        baseline_key = InjectionStrategy.BASELINE.value
        improvements: Dict[str, Dict[str, float]] = {}
        baseline_metrics = strategy_metrics.get(baseline_key, {})
        for s_name, s_metrics in strategy_metrics.items():
            if s_name == baseline_key:
                improvements[s_name] = {k: 0.0 for k in s_metrics}
                continue
            imp: Dict[str, float] = {}
            for metric_key in [
                EvaluationMetric.BEHAVIOR_ADHERENCE.value,
                EvaluationMetric.CITATION_ACCURACY.value,
            ]:
                base_val = baseline_metrics.get(metric_key, 0)
                cand_val = s_metrics.get(metric_key, 0)
                imp[metric_key] = (cand_val - base_val) / base_val if base_val > 0 else cand_val
            # Hallucination: lower is better
            base_hall = baseline_metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
            cand_hall = s_metrics.get(EvaluationMetric.HALLUCINATION_RATE.value, 0)
            imp[EvaluationMetric.HALLUCINATION_RATE.value] = (
                (base_hall - cand_hall) / base_hall if base_hall > 0 else -cand_hall
            )
            improvements[s_name] = imp

        # Token accounting
        token_accounting: Dict[str, Dict[str, float]] = {}
        baseline_tokens = baseline_metrics.get("total_tokens", 0)
        for s_name, s_metrics in strategy_metrics.items():
            total = s_metrics.get("total_tokens", 0)
            savings = baseline_tokens - total
            pct = savings / baseline_tokens if baseline_tokens > 0 else 0.0
            token_accounting[s_name] = {
                "total_tokens": total,
                "token_savings": savings,
                "token_savings_pct": round(pct, 4),
            }

        # Determine winner (highest behavior adherence among non-baseline)
        best_strategy = baseline_key
        best_adherence = baseline_metrics.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0)
        for s_name, s_metrics in strategy_metrics.items():
            adh = s_metrics.get(EvaluationMetric.BEHAVIOR_ADHERENCE.value, 0)
            if adh > best_adherence:
                best_adherence = adh
                best_strategy = s_name

        return StrategyComparisonResult(
            comparison_id=comparison_id,
            model_id=model_id,
            benchmark_name=bench.name,
            started_at=started_at,
            completed_at=datetime.utcnow(),
            total_examples=len(examples),
            strategy_results=strategy_results,
            strategy_metrics=strategy_metrics,
            improvements=improvements,
            token_accounting=token_accounting,
            winner=best_strategy,
            status="completed",
        )

    def _build_strategy_benchmark(
        self,
        original: Benchmark,
        examples: List[BenchmarkExample],
        strategy: InjectionStrategy,
        prompt_builder: Optional[Callable] = None,
    ) -> Benchmark:
        """Build a benchmark copy whose context field encodes the injection strategy.

        For the default builder:
        - BASELINE: no extra context
        - BCI_ONLY: context includes "[BCI] Retrieved behaviors: ..."
        - PACK_BCI: context includes "[PACK+BCI] Knowledge pack + behaviors: ..."
        """
        new_examples: List[BenchmarkExample] = []
        for ex in examples:
            if prompt_builder:
                # Custom builder returns messages, but we encode via context for now
                msgs = prompt_builder(strategy, ex)
                ctx = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "system")
            else:
                ctx = self._default_strategy_context(strategy, ex)
            new_examples.append(BenchmarkExample(
                example_id=f"{ex.example_id}_{strategy.value}",
                prompt=ex.prompt,
                expected_behaviors=ex.expected_behaviors,
                context=ctx or ex.context,
                expected_response_contains=ex.expected_response_contains,
                expected_response_excludes=ex.expected_response_excludes,
                difficulty=ex.difficulty,
                category=ex.category,
            ))
        return Benchmark(
            name=f"{original.name}_{strategy.value}",
            description=f"{original.description} [{strategy.value}]",
            examples=new_examples,
            version=original.version,
            created_at=original.created_at,
        )

    @staticmethod
    def _default_strategy_context(strategy: InjectionStrategy, ex: BenchmarkExample) -> Optional[str]:
        """Build default context string for a given injection strategy."""
        if strategy == InjectionStrategy.BASELINE:
            return None
        elif strategy == InjectionStrategy.BCI_ONLY:
            behaviors_str = ", ".join(ex.expected_behaviors) if ex.expected_behaviors else "none"
            return f"[BCI] Retrieved behaviors: {behaviors_str}. Apply these behaviors in your response."
        elif strategy == InjectionStrategy.PACK_BCI:
            behaviors_str = ", ".join(ex.expected_behaviors) if ex.expected_behaviors else "none"
            base_ctx = ex.context or ""
            return (
                f"[PACK+BCI] Knowledge pack active. {base_ctx} "
                f"Retrieved behaviors: {behaviors_str}. "
                f"Apply the knowledge pack overlays and cited behaviors."
            ).strip()
        return None

    def check_regression_anchors(
        self,
        strategy_result: StrategyComparisonResult,
        anchors_path: str,
    ) -> Dict[str, Any]:
        """Check strategy comparison results against regression anchor thresholds.

        Args:
            strategy_result: Output of compare_injection_strategies().
            anchors_path: Path to regression_anchors.json.

        Returns:
            Dict with 'passed' (bool), 'failures' (list of failures),
            and 'summary' per strategy.
        """
        with open(anchors_path) as f:
            anchors = json.load(f)

        global_thresholds = anchors.get("global_thresholds", {})
        comparison_thresholds = anchors.get("comparison_thresholds", {})
        failures: List[Dict[str, Any]] = []
        summary: Dict[str, Dict[str, Any]] = {}

        for s_name, s_metrics in strategy_result.strategy_metrics.items():
            s_failures: List[str] = []

            # Check global thresholds
            for metric_name, thresh in global_thresholds.items():
                val = s_metrics.get(metric_name)
                if val is None:
                    continue
                if "min" in thresh and val < thresh["min"]:
                    s_failures.append(
                        f"{metric_name}: {val:.4f} < min {thresh['min']}"
                    )
                if "max" in thresh and val > thresh["max"]:
                    s_failures.append(
                        f"{metric_name}: {val:.4f} > max {thresh['max']}"
                    )

            summary[s_name] = {
                "metrics": s_metrics,
                "failures": s_failures,
                "passed": len(s_failures) == 0,
            }
            for f_msg in s_failures:
                failures.append({"strategy": s_name, "failure": f_msg})

        # Check comparison thresholds (strategy vs baseline)
        for comp_key, comp_thresh in comparison_thresholds.items():
            # Map comp_key to strategy
            if comp_key == "pack_bci_vs_baseline":
                target = InjectionStrategy.PACK_BCI.value
            elif comp_key == "bci_only_vs_baseline":
                target = InjectionStrategy.BCI_ONLY.value
            else:
                continue
            imp = strategy_result.improvements.get(target, {})
            for imp_key, min_val in comp_thresh.items():
                if imp_key == "description":
                    continue
                if imp_key.startswith("min_improvement_"):
                    metric = imp_key.replace("min_improvement_", "")
                    actual = imp.get(metric, 0)
                    if actual < min_val:
                        failures.append({
                            "strategy": target,
                            "failure": f"{comp_key}.{imp_key}: {actual:.4f} < {min_val}",
                        })

        # Token efficiency
        token_thresh = comparison_thresholds.get("token_efficiency", {})
        max_increase = token_thresh.get("max_token_increase_percent", 100)
        for s_name, t_acct in strategy_result.token_accounting.items():
            savings_pct = t_acct.get("token_savings_pct", 0)
            if savings_pct < -(max_increase / 100):
                failures.append({
                    "strategy": s_name,
                    "failure": (
                        f"Token increase {-savings_pct*100:.1f}% exceeds "
                        f"max {max_increase}%"
                    ),
                })

        return {
            "passed": len(failures) == 0,
            "failures": failures,
            "summary": summary,
        }

    def get_benchmark(self, name: str) -> Optional[Benchmark]:
        """Get a benchmark by name."""
        if name in self._benchmarks:
            return self._benchmarks[name]

        # Try to load from file
        path = os.path.join(self._benchmarks_dir, f"{name}.json")
        if os.path.exists(path):
            bench = Benchmark.load(path)
            self._benchmarks[name] = bench
            return bench

        # Check for built-in benchmarks
        if name == "behavior_adherence":
            return self._create_default_benchmark()

        return None

    def register_benchmark(self, benchmark: Benchmark, save: bool = True) -> None:
        """Register a benchmark."""
        self._benchmarks[benchmark.name] = benchmark
        if save:
            path = os.path.join(self._benchmarks_dir, f"{benchmark.name}.json")
            benchmark.save(path)
            logger.info("Saved benchmark to %s", path)

    def list_benchmarks(self) -> List[str]:
        """List available benchmarks."""
        benchmarks = list(self._benchmarks.keys())

        # Add file-based benchmarks
        if os.path.exists(self._benchmarks_dir):
            for filename in os.listdir(self._benchmarks_dir):
                if filename.endswith(".json"):
                    name = filename[:-5]
                    if name not in benchmarks:
                        benchmarks.append(name)

        # Add built-in
        if "behavior_adherence" not in benchmarks:
            benchmarks.append("behavior_adherence")

        return benchmarks

    def _score_behavior_adherence(
        self,
        response: str,
        expected_behaviors: List[str],
    ) -> float:
        """Score how well the response adheres to expected behaviors.

        Checks for:
        1. Behavior citations (backtick format)
        2. Behavior name mentions
        3. Role annotations (Student/Teacher/Strategist)
        """
        if not expected_behaviors:
            return 1.0

        score = 0.0
        for behavior in expected_behaviors:
            # Full citation: `behavior_name` (Role)
            citation_pattern = rf"`{re.escape(behavior)}`\s*\([^)]+\)"
            if re.search(citation_pattern, response):
                score += 1.0
            # Partial citation: `behavior_name`
            elif f"`{behavior}`" in response:
                score += 0.8
            # Just mentioned
            elif behavior in response:
                score += 0.5
            # Behavior concept mentioned (without exact name)
            elif behavior.replace("behavior_", "").replace("_", " ") in response.lower():
                score += 0.3

        return score / len(expected_behaviors)

    def _score_citation_accuracy(
        self,
        response: str,
        expected_behaviors: List[str],
    ) -> float:
        """Score citation format accuracy."""
        # Find all citations in response
        citations = re.findall(r"`(behavior_[a-z_]+)`", response)

        if not citations:
            return 0.0

        # Check if citations are valid
        valid_citations = [c for c in citations if c in expected_behaviors]
        accuracy = len(valid_citations) / len(citations) if citations else 0.0

        # Bonus for proper role annotation
        role_citations = re.findall(r"`behavior_[a-z_]+`\s*\((Student|Teacher|Metacognitive Strategist)\)", response)
        if role_citations:
            accuracy = min(1.0, accuracy + 0.1)

        return accuracy

    def _detect_hallucinations(
        self,
        response: str,
        expected_behaviors: List[str],
        forbidden_content: Optional[List[str]] = None,
    ) -> float:
        """Detect hallucination rate (0 = no hallucinations, 1 = all hallucinations).

        Checks for:
        1. Made-up behavior names
        2. Forbidden content
        3. Confident but wrong statements
        """
        hallucination_score = 0.0
        checks = 0

        # Check for made-up behaviors
        cited_behaviors = re.findall(r"`(behavior_[a-z_]+)`", response)
        if cited_behaviors:
            fake_behaviors = [b for b in cited_behaviors if b not in expected_behaviors]
            if fake_behaviors:
                hallucination_score += len(fake_behaviors) / len(cited_behaviors)
            checks += 1

        # Check for forbidden content
        if forbidden_content:
            for forbidden in forbidden_content:
                if forbidden.lower() in response.lower():
                    hallucination_score += 1.0
                    checks += 1
            if not any(f.lower() in response.lower() for f in forbidden_content):
                checks += 1  # Passed the check

        return hallucination_score / max(checks, 1)

    def _calculate_cost(self, model_id: str, total_tokens: int) -> float:
        """Calculate cost for token usage."""
        # Determine pricing tier
        if model_id.startswith("ft:gpt-4o-mini"):
            pricing = self._pricing["ft:gpt-4o-mini"]
        elif model_id.startswith("ft:gpt-4o"):
            pricing = self._pricing["ft:gpt-4o"]
        elif "gpt-4o-mini" in model_id:
            pricing = self._pricing["gpt-4o-mini"]
        elif "gpt-4o" in model_id:
            pricing = self._pricing["gpt-4o"]
        else:
            pricing = self._pricing["gpt-4o-mini"]  # Default

        # Approximate 50/50 split between input and output
        input_tokens = total_tokens // 2
        output_tokens = total_tokens - input_tokens

        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000
        return round(cost, 4)

    def _create_default_benchmark(self) -> Benchmark:
        """Create default behavior adherence benchmark."""
        examples = [
            BenchmarkExample(
                example_id="ba-001",
                prompt="How should I add logging to my new API endpoint?",
                expected_behaviors=["behavior_use_raze_for_logging"],
                expected_response_contains=["Raze", "RazeLogger"],
                category="logging",
            ),
            BenchmarkExample(
                example_id="ba-002",
                prompt="I need to set up a development environment for our service.",
                expected_behaviors=["behavior_use_breakeramp_for_environments"],
                expected_response_contains=["BreakerAmp", "blueprint"],
                category="environments",
            ),
            BenchmarkExample(
                example_id="ba-003",
                prompt="What's the best way to call external APIs in this project?",
                expected_behaviors=["behavior_prefer_mcp_tools"],
                expected_response_contains=["MCP"],
                category="tooling",
            ),
            BenchmarkExample(
                example_id="ba-004",
                prompt="I found a hardcoded API key in the code. What should I do?",
                expected_behaviors=["behavior_prevent_secret_leaks", "behavior_rotate_leaked_credentials"],
                expected_response_contains=["rotate", "secret"],
                category="security",
            ),
            BenchmarkExample(
                example_id="ba-005",
                prompt="How do I create a reusable package for our shared utilities?",
                expected_behaviors=["behavior_extract_standalone_package"],
                expected_response_contains=["packages/", "pyproject.toml"],
                category="architecture",
            ),
        ]

        return Benchmark(
            name="behavior_adherence",
            description="Default benchmark for testing behavior-conditioned responses",
            examples=examples,
            version="1.0",
            created_at=datetime.utcnow(),
        )


def generate_benchmark_from_agents_md(
    agents_md_path: str,
    *,
    examples_per_behavior: int = 3,
    output_path: Optional[str] = None,
) -> Benchmark:
    """Generate a benchmark from AGENTS.md behaviors.

    Parses the AGENTS.md file to extract behavior definitions and
    generates evaluation examples for each behavior.

    Args:
        agents_md_path: Path to AGENTS.md file.
        examples_per_behavior: Number of examples per behavior.
        output_path: Optional path to save benchmark JSON.

    Returns:
        Generated Benchmark.
    """
    with open(agents_md_path) as f:
        content = f.read()

    # Parse behaviors from markdown
    behaviors: List[Dict[str, Any]] = []

    # Find behavior definitions (### `behavior_xxx` format)
    behavior_pattern = r"###\s*`(behavior_[a-z_]+)`\s*\n(.*?)(?=###|$)"
    matches = re.findall(behavior_pattern, content, re.DOTALL)

    for behavior_id, body in matches:
        # Extract "When" triggers
        when_match = re.search(r"\*\*When\*\*:\s*([^\n]+(?:\n-[^\n]+)*)", body)
        when_text = when_match.group(1).strip() if when_match else ""

        # Extract steps
        steps_match = re.search(r"\*\*Steps\*\*:\s*((?:\n\s*\d+\..*)+)", body)
        steps_text = steps_match.group(1).strip() if steps_match else ""

        behaviors.append({
            "behavior_id": behavior_id,
            "when": when_text,
            "steps": steps_text,
        })

    logger.info("Parsed %d behaviors from AGENTS.md", len(behaviors))

    # Generate examples
    examples: List[BenchmarkExample] = []

    prompt_templates = [
        "How do I {action}?",
        "What's the best practice for {action}?",
        "I need help with {action}. What should I do?",
    ]

    for behavior in behaviors:
        behavior_id = behavior["behavior_id"]
        when_text = behavior["when"]

        # Generate action from behavior name
        action = behavior_id.replace("behavior_", "").replace("_", " ")

        for i in range(examples_per_behavior):
            template = prompt_templates[i % len(prompt_templates)]
            prompt = template.format(action=action)

            # Add context from "when" triggers
            context = when_text[:200] if when_text else None

            examples.append(BenchmarkExample(
                example_id=f"{behavior_id}-{i+1:02d}",
                prompt=prompt,
                expected_behaviors=[behavior_id],
                context=context,
                category=action.split()[0] if action else "general",
            ))

    benchmark = Benchmark(
        name="agents_md_benchmark",
        description=f"Auto-generated from AGENTS.md ({len(behaviors)} behaviors)",
        examples=examples,
        version="1.0",
        created_at=datetime.utcnow(),
    )

    if output_path:
        benchmark.save(output_path)
        logger.info("Saved benchmark to %s (%d examples)", output_path, len(examples))

    return benchmark


def load_domain_benchmark(benchmarks_dir: Optional[str] = None) -> Benchmark:
    """Load the domain expertise benchmark from JSONL.

    Args:
        benchmarks_dir: Directory containing domain_expertise_benchmark.jsonl.
            Defaults to the package's benchmarks/ directory.

    Returns:
        Benchmark loaded from the JSONL file.
    """
    if benchmarks_dir is None:
        benchmarks_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "benchmarks",
        )
    jsonl_path = os.path.join(benchmarks_dir, "domain_expertise_benchmark.jsonl")
    examples: List[BenchmarkExample] = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            examples.append(BenchmarkExample.from_dict(data))
    return Benchmark(
        name="domain_expertise",
        description=f"Domain expertise benchmark ({len(examples)} examples across task families and GEP phases)",
        examples=examples,
        version="1.0",
        created_at=datetime.utcnow(),
    )


def load_regression_anchors(benchmarks_dir: Optional[str] = None) -> Dict[str, Any]:
    """Load regression anchor thresholds.

    Args:
        benchmarks_dir: Directory containing regression_anchors.json.
            Defaults to the package's benchmarks/ directory.

    Returns:
        Parsed JSON dict with threshold definitions.
    """
    if benchmarks_dir is None:
        benchmarks_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "benchmarks",
        )
    anchors_path = os.path.join(benchmarks_dir, "regression_anchors.json")
    with open(anchors_path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Quality Gate Service — CI & pre-promotion gates (T4.3.3)
# ---------------------------------------------------------------------------


@dataclass
class QualityGateResult:
    """Result of a quality gate evaluation."""

    gate_name: str
    passed: bool
    score: float
    threshold: float
    details: Dict[str, Any] = field(default_factory=dict)
    failures: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "score": self.score,
            "threshold": self.threshold,
            "details": self.details,
            "failures": list(self.failures),
        }


@dataclass
class QualityGateReport:
    """Aggregated report of all quality gate checks."""

    gates: List[QualityGateResult] = field(default_factory=list)
    overall_passed: bool = True
    regression_detected: bool = False
    regression_details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_passed": self.overall_passed,
            "gates": [g.to_dict() for g in self.gates],
            "total_gates": len(self.gates),
            "passed_gates": sum(1 for g in self.gates if g.passed),
            "failed_gates": sum(1 for g in self.gates if not g.passed),
            "regression_detected": self.regression_detected,
            "regression_details": self.regression_details,
        }


class QualityGateService:
    """Enforces quality thresholds for behavior promotions, pack builds, and CI.

    Gates:
    - pre_approval: checks a single behavior's adherence score before promotion
    - pack_validation: checks strategy comparison results after pack build
    - regression_check: compares current benchmark results to previous baseline
    """

    DEFAULT_BEHAVIOR_ADHERENCE_MIN = 0.7
    DEFAULT_CITATION_ACCURACY_MIN = 0.65
    DEFAULT_HALLUCINATION_MAX = 0.10
    DEFAULT_REGRESSION_THRESHOLD = 0.05  # 5% degradation triggers flag

    def __init__(
        self,
        *,
        behavior_adherence_min: float = DEFAULT_BEHAVIOR_ADHERENCE_MIN,
        citation_accuracy_min: float = DEFAULT_CITATION_ACCURACY_MIN,
        hallucination_max: float = DEFAULT_HALLUCINATION_MAX,
        regression_threshold: float = DEFAULT_REGRESSION_THRESHOLD,
        anchors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.behavior_adherence_min = behavior_adherence_min
        self.citation_accuracy_min = citation_accuracy_min
        self.hallucination_max = hallucination_max
        self.regression_threshold = regression_threshold
        self._anchors = anchors

    @property
    def anchors(self) -> Dict[str, Any]:
        if self._anchors is None:
            self._anchors = load_regression_anchors()
        return self._anchors

    # ------------------------------------------------------------------
    # Gate: Pre-approval behavior check
    # ------------------------------------------------------------------

    def check_behavior_approval(
        self,
        behavior_id: str,
        adherence_score: float,
        citation_score: float = 0.0,
        hallucination_rate: float = 0.0,
    ) -> QualityGateResult:
        """Gate for behavior promotion — checks minimum quality thresholds.

        Args:
            behavior_id: The behavior being promoted.
            adherence_score: Measured behavior adherence (0.0-1.0).
            citation_score: Measured citation accuracy (0.0-1.0).
            hallucination_rate: Measured hallucination rate (0.0-1.0).

        Returns:
            QualityGateResult indicating pass/fail.
        """
        failures: List[str] = []
        if adherence_score < self.behavior_adherence_min:
            failures.append(
                f"behavior_adherence {adherence_score:.4f} < min {self.behavior_adherence_min}"
            )
        if citation_score > 0 and citation_score < self.citation_accuracy_min:
            failures.append(
                f"citation_accuracy {citation_score:.4f} < min {self.citation_accuracy_min}"
            )
        if hallucination_rate > self.hallucination_max:
            failures.append(
                f"hallucination_rate {hallucination_rate:.4f} > max {self.hallucination_max}"
            )

        passed = len(failures) == 0
        return QualityGateResult(
            gate_name="pre_approval",
            passed=passed,
            score=adherence_score,
            threshold=self.behavior_adherence_min,
            details={
                "behavior_id": behavior_id,
                "adherence_score": adherence_score,
                "citation_score": citation_score,
                "hallucination_rate": hallucination_rate,
            },
            failures=failures,
        )

    # ------------------------------------------------------------------
    # Gate: Pack build validation
    # ------------------------------------------------------------------

    def check_pack_validation(
        self,
        strategy_result: StrategyComparisonResult,
        anchors_path: Optional[str] = None,
    ) -> QualityGateResult:
        """Gate for pack release — validates strategy comparison against anchors.

        Args:
            strategy_result: Output of compare_injection_strategies().
            anchors_path: Path to regression_anchors.json (uses default if None).

        Returns:
            QualityGateResult summarizing whether pack meets thresholds.
        """
        if anchors_path:
            with open(anchors_path) as f:
                anchors = json.load(f)
        else:
            anchors = self.anchors

        # Reuse EvaluationService.check_regression_anchors logic
        failures: List[str] = []
        global_thresholds = anchors.get("global_thresholds", {})
        comparison_thresholds = anchors.get("comparison_thresholds", {})

        # Check pack_bci strategy metrics against global thresholds
        pack_metrics = strategy_result.strategy_metrics.get("pack_bci", {})
        for metric_name, thresh in global_thresholds.items():
            val = pack_metrics.get(metric_name)
            if val is None:
                continue
            if "min" in thresh and val < thresh["min"]:
                failures.append(f"pack_bci.{metric_name}: {val:.4f} < min {thresh['min']}")
            if "max" in thresh and val > thresh["max"]:
                failures.append(f"pack_bci.{metric_name}: {val:.4f} > max {thresh['max']}")

        # Check improvement over baseline
        pack_bci_thresh = comparison_thresholds.get("pack_bci_vs_baseline", {})
        pack_improvements = strategy_result.improvements.get("pack_bci", {})
        for key, min_val in pack_bci_thresh.items():
            if key == "description":
                continue
            if key.startswith("min_improvement_"):
                metric = key.replace("min_improvement_", "")
                actual = pack_improvements.get(metric, 0)
                if actual < min_val:
                    failures.append(f"improvement.{metric}: {actual:.4f} < min {min_val}")

        # Primary score = pack_bci behavior adherence
        score = pack_metrics.get("behavior_adherence", 0.0)
        passed = len(failures) == 0

        return QualityGateResult(
            gate_name="pack_validation",
            passed=passed,
            score=score,
            threshold=global_thresholds.get("behavior_adherence", {}).get("min", self.behavior_adherence_min),
            details={
                "strategy_metrics": strategy_result.strategy_metrics,
                "improvements": strategy_result.improvements,
            },
            failures=failures,
        )

    # ------------------------------------------------------------------
    # Gate: Regression detection
    # ------------------------------------------------------------------

    def check_regression(
        self,
        current_metrics: Dict[str, float],
        previous_metrics: Dict[str, float],
    ) -> QualityGateResult:
        """Compare current benchmark metrics against previous baseline.

        Flags a regression if any key metric degrades by more than the
        configured regression_threshold (default 5%).

        Args:
            current_metrics: Current benchmark run metrics.
            previous_metrics: Previous benchmark run metrics (the baseline).

        Returns:
            QualityGateResult with regression details.
        """
        regressions: List[str] = []
        details: Dict[str, Any] = {"comparisons": {}}

        for metric in ("behavior_adherence", "citation_accuracy", "mrr"):
            curr = current_metrics.get(metric)
            prev = previous_metrics.get(metric)
            if curr is None or prev is None or prev == 0:
                continue
            delta_pct = (curr - prev) / prev
            details["comparisons"][metric] = {
                "current": curr,
                "previous": prev,
                "delta_pct": delta_pct,
            }
            if delta_pct < -self.regression_threshold:
                regressions.append(
                    f"{metric} regressed {abs(delta_pct)*100:.1f}% "
                    f"(prev={prev:.4f}, curr={curr:.4f}, threshold={self.regression_threshold*100:.0f}%)"
                )

        # Also check hallucination increase
        for metric in ("hallucination_rate",):
            curr = current_metrics.get(metric)
            prev = previous_metrics.get(metric)
            if curr is None or prev is None:
                continue
            # For hallucination, increasing is bad
            if prev > 0:
                delta_pct = (curr - prev) / prev
            else:
                delta_pct = curr  # was 0, any increase is bad
            details["comparisons"][metric] = {
                "current": curr,
                "previous": prev,
                "delta_pct": delta_pct,
            }
            if delta_pct > self.regression_threshold:
                regressions.append(
                    f"{metric} increased {abs(delta_pct)*100:.1f}% "
                    f"(prev={prev:.4f}, curr={curr:.4f}, threshold={self.regression_threshold*100:.0f}%)"
                )

        adherence = current_metrics.get("behavior_adherence", 0.0)
        passed = len(regressions) == 0

        return QualityGateResult(
            gate_name="regression_check",
            passed=passed,
            score=adherence,
            threshold=self.regression_threshold,
            details=details,
            failures=regressions,
        )

    # ------------------------------------------------------------------
    # Run all gates
    # ------------------------------------------------------------------

    def run_all_gates(
        self,
        *,
        strategy_result: Optional[StrategyComparisonResult] = None,
        previous_metrics: Optional[Dict[str, float]] = None,
        anchors_path: Optional[str] = None,
    ) -> QualityGateReport:
        """Run all applicable quality gates and return an aggregated report.

        Args:
            strategy_result: If provided, runs pack_validation gate.
            previous_metrics: If provided, runs regression_check gate against
                the pack_bci strategy metrics from strategy_result.
            anchors_path: Optional path to regression_anchors.json.

        Returns:
            QualityGateReport with all gate results.
        """
        report = QualityGateReport()

        if strategy_result is not None:
            pack_gate = self.check_pack_validation(
                strategy_result, anchors_path=anchors_path
            )
            report.gates.append(pack_gate)

            if previous_metrics is not None:
                current_metrics = strategy_result.strategy_metrics.get("pack_bci", {})
                reg_gate = self.check_regression(current_metrics, previous_metrics)
                report.gates.append(reg_gate)
                report.regression_detected = not reg_gate.passed
                if not reg_gate.passed:
                    report.regression_details = reg_gate.details

        report.overall_passed = all(g.passed for g in report.gates)
        return report
