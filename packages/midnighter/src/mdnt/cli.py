"""Midnighter CLI - Behavior-Conditioned SFT Training Pipeline.

Provides command-line interface for:
- Corpus management (list, create, generate, export)
- Training job management (start, list, status, cancel)
- Model registry (list, info, evaluate)
- Evaluation and benchmarking

Usage:
    mdnt corpus list
    mdnt corpus create --name my-corpus --behaviors "behavior_*"
    mdnt corpus generate --from-agents-md ./AGENTS.md --output corpus.jsonl

    mdnt job start --corpus-id abc123 --model gpt-4o-mini
    mdnt job list
    mdnt job status <job-id>
    mdnt job cancel <job-id>

    mdnt model list
    mdnt model evaluate <model-id> --benchmark behavior_adherence

    mdnt benchmark list
    mdnt benchmark generate --from-agents-md ./AGENTS.md --output benchmark.json
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("mdnt")


def get_service():
    """Lazy import and create MidnighterService."""
    from mdnt.service import MidnighterService
    return MidnighterService()


def get_openai_client():
    """Lazy import and create OpenAI client."""
    from mdnt.clients.openai import OpenAIFineTuningClient
    return OpenAIFineTuningClient()


def get_evaluation_service():
    """Lazy import and create EvaluationService."""
    from mdnt.evaluation import EvaluationService
    return EvaluationService()


def format_datetime(dt: Optional[datetime]) -> str:
    """Format datetime for display."""
    if dt is None:
        return "-"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_json(data: Any) -> str:
    """Format data as JSON."""
    return json.dumps(data, indent=2, default=str)


# ============================================================================
# Main CLI Group
# ============================================================================

@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output")
@click.option("--quiet", "-q", is_flag=True, help="Suppress non-essential output")
@click.version_option(version="0.1.0", prog_name="mdnt")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool) -> None:
    """Midnighter - Behavior-Conditioned SFT Training Pipeline.

    Train language models to follow behavior-conditioned guidelines using
    Meta's Metacognitive Reuse methodology.

    \b
    Quick Start:
      1. Generate a corpus: mdnt corpus generate --from-agents-md ./AGENTS.md
      2. Start training:    mdnt job start --corpus corpus.jsonl
      3. Monitor progress:  mdnt job status <job-id>
      4. Evaluate model:    mdnt model evaluate <model-id>

    For more information, see: https://github.com/org/amprealize/packages/midnighter
    """
    ctx.ensure_object(dict)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.WARNING)


# ============================================================================
# Corpus Commands
# ============================================================================

@cli.group()
def corpus() -> None:
    """Manage training corpora.

    A corpus is a collection of training examples in the BC-SFT format,
    where each example includes a prompt, expected behaviors, and a
    model response that demonstrates behavior adherence.
    """
    pass


@corpus.command("list")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def corpus_list(output_format: str) -> None:
    """List all training corpora."""
    try:
        service = get_service()
        corpora = service.list_corpora()

        if output_format == "json":
            click.echo(format_json([c.to_dict() for c in corpora]))
        else:
            if not corpora:
                click.echo("No corpora found.")
                return

            click.echo(f"\n{'ID':<36}  {'Name':<30}  {'Examples':<10}  {'Created':<20}")
            click.echo("-" * 100)
            for c in corpora:
                click.echo(
                    f"{c.corpus_id:<36}  {c.name[:30]:<30}  {c.example_count:<10}  "
                    f"{format_datetime(c.created_at):<20}"
                )
            click.echo(f"\nTotal: {len(corpora)} corpora")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@corpus.command("create")
@click.option("--name", "-n", required=True, help="Corpus name")
@click.option("--description", "-d", default="", help="Corpus description")
@click.option("--behaviors", "-b", multiple=True, help="Behaviors to include (glob patterns)")
@click.option("--examples-per-behavior", "-e", default=5, type=int, help="Examples per behavior")
@click.option("--output", "-o", type=click.Path(), help="Output JSONL file path")
def corpus_create(
    name: str,
    description: str,
    behaviors: tuple,
    examples_per_behavior: int,
    output: Optional[str],
) -> None:
    """Create a new training corpus."""
    try:
        service = get_service()

        # Convert behaviors tuple to list
        behavior_list = list(behaviors) if behaviors else None

        click.echo(f"Creating corpus '{name}'...")
        corpus_obj = service.create_corpus(
            name=name,
            description=description,
            behavior_patterns=behavior_list,
            examples_per_behavior=examples_per_behavior,
        )

        click.echo(f"Created corpus: {corpus_obj.corpus_id}")
        click.echo(f"Examples: {corpus_obj.example_count}")

        if output:
            service.export_corpus(corpus_obj.corpus_id, output)
            click.echo(f"Exported to: {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@corpus.command("generate")
@click.option("--from-agents-md", "-a", type=click.Path(exists=True), help="Path to AGENTS.md")
@click.option("--from-behaviors", "-b", type=click.Path(exists=True), help="Path to behaviors JSON")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output JSONL file path")
@click.option("--examples-per-behavior", "-e", default=3, type=int, help="Examples per behavior")
@click.option("--system-prompt", "-s", help="Custom system prompt")
def corpus_generate(
    from_agents_md: Optional[str],
    from_behaviors: Optional[str],
    output: str,
    examples_per_behavior: int,
    system_prompt: Optional[str],
) -> None:
    """Generate a training corpus from AGENTS.md or behavior definitions."""
    try:
        service = get_service()

        if from_agents_md:
            click.echo(f"Generating corpus from {from_agents_md}...")
            corpus_obj = service.generate_corpus_from_agents_md(
                agents_md_path=from_agents_md,
                examples_per_behavior=examples_per_behavior,
                system_prompt=system_prompt,
            )
        elif from_behaviors:
            click.echo(f"Generating corpus from {from_behaviors}...")
            with open(from_behaviors) as f:
                behaviors = json.load(f)
            corpus_obj = service.generate_corpus_from_behaviors(
                behaviors=behaviors,
                examples_per_behavior=examples_per_behavior,
                system_prompt=system_prompt,
            )
        else:
            click.echo("Error: Specify --from-agents-md or --from-behaviors", err=True)
            sys.exit(1)

        # Export to JSONL
        service.export_corpus(corpus_obj.corpus_id, output)

        click.echo(f"\nGenerated corpus: {corpus_obj.corpus_id}")
        click.echo(f"Examples: {corpus_obj.example_count}")
        click.echo(f"Output: {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@corpus.command("export")
@click.argument("corpus_id")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output file path")
@click.option("--format", "output_format", type=click.Choice(["jsonl", "json"]), default="jsonl")
def corpus_export(corpus_id: str, output: str, output_format: str) -> None:
    """Export a corpus to a file."""
    try:
        service = get_service()
        service.export_corpus(corpus_id, output, format=output_format)
        click.echo(f"Exported corpus {corpus_id} to {output}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@corpus.command("info")
@click.argument("corpus_id")
def corpus_info(corpus_id: str) -> None:
    """Show details about a corpus."""
    try:
        service = get_service()
        corpus_obj = service.get_corpus(corpus_id)

        if not corpus_obj:
            click.echo(f"Corpus not found: {corpus_id}", err=True)
            sys.exit(1)

        click.echo(format_json(corpus_obj.to_dict()))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Job Commands
# ============================================================================

@cli.group()
def job() -> None:
    """Manage fine-tuning jobs.

    Fine-tuning jobs train a base model on your corpus to create a
    behavior-conditioned model that follows your defined behaviors.
    """
    pass


@job.command("start")
@click.option("--corpus", "-c", required=True, help="Corpus ID or JSONL file path")
@click.option("--model", "-m", default="gpt-4o-mini-2024-07-18", help="Base model to fine-tune")
@click.option("--suffix", "-s", default="mdnt-bcsft", help="Model suffix")
@click.option("--epochs", "-e", default=3, type=int, help="Number of training epochs")
@click.option("--wait/--no-wait", default=False, help="Wait for job completion")
def job_start(
    corpus: str,
    model: str,
    suffix: str,
    epochs: int,
    wait: bool,
) -> None:
    """Start a fine-tuning job."""
    try:
        client = get_openai_client()

        # Check if corpus is a file path or ID
        if os.path.exists(corpus):
            click.echo(f"Uploading training file: {corpus}")
            with open(corpus) as f:
                training_data = f.read()
            file_obj = client.upload_training_file(training_data)
            training_file = file_obj.file_id
            click.echo(f"Uploaded file: {training_file}")
        else:
            # Assume it's a file ID or fetch from service
            training_file = corpus

        click.echo(f"\nStarting fine-tuning job...")
        click.echo(f"  Model: {model}")
        click.echo(f"  Suffix: {suffix}")
        click.echo(f"  Epochs: {epochs}")

        job_obj = client.create_job(
            training_file=training_file,
            model=model,
            suffix=suffix,
            hyperparameters={"n_epochs": epochs},
        )

        click.echo(f"\nJob created: {job_obj.job_id}")
        click.echo(f"Status: {job_obj.status.value}")

        if wait:
            click.echo("\nWaiting for completion...")

            def progress_callback(j):
                click.echo(f"  Status: {j.status.value} (tokens: {j.trained_tokens})")

            final_job = client.wait_for_completion(
                job_obj.job_id,
                callback=progress_callback,
            )

            if final_job.fine_tuned_model:
                click.echo(f"\n✓ Training complete!")
                click.echo(f"  Model: {final_job.fine_tuned_model}")
                click.echo(f"  Tokens: {final_job.trained_tokens:,}")
            else:
                click.echo(f"\n✗ Training failed: {final_job.error}")
                sys.exit(1)
        else:
            click.echo(f"\nMonitor with: mdnt job status {job_obj.job_id}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@job.command("list")
@click.option("--limit", "-l", default=20, type=int, help="Maximum jobs to show")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def job_list(limit: int, output_format: str) -> None:
    """List fine-tuning jobs."""
    try:
        client = get_openai_client()
        jobs = client.list_jobs(limit=limit)

        if output_format == "json":
            click.echo(format_json([j.to_dict() for j in jobs]))
        else:
            if not jobs:
                click.echo("No jobs found.")
                return

            click.echo(f"\n{'Job ID':<36}  {'Model':<25}  {'Status':<15}  {'Created':<20}")
            click.echo("-" * 100)
            for j in jobs:
                status_color = {
                    "succeeded": "green",
                    "failed": "red",
                    "cancelled": "yellow",
                    "running": "blue",
                }.get(j.status.value, "white")

                click.echo(
                    f"{j.job_id:<36}  {j.model[:25]:<25}  "
                    f"{click.style(j.status.value, fg=status_color):<15}  "
                    f"{format_datetime(j.created_at):<20}"
                )
            click.echo(f"\nShowing {len(jobs)} jobs")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@job.command("status")
@click.argument("job_id")
@click.option("--events/--no-events", default=False, help="Show job events")
def job_status(job_id: str, events: bool) -> None:
    """Show status of a fine-tuning job."""
    try:
        client = get_openai_client()
        job_obj = client.get_job(job_id)

        click.echo(f"\nJob: {job_obj.job_id}")
        click.echo(f"Status: {job_obj.status.value}")
        click.echo(f"Model: {job_obj.model}")
        click.echo(f"Created: {format_datetime(job_obj.created_at)}")

        if job_obj.finished_at:
            click.echo(f"Finished: {format_datetime(job_obj.finished_at)}")

        if job_obj.trained_tokens:
            click.echo(f"Trained Tokens: {job_obj.trained_tokens:,}")

        if job_obj.fine_tuned_model:
            click.echo(f"\n✓ Fine-tuned Model: {job_obj.fine_tuned_model}")

        if job_obj.error:
            click.echo(f"\n✗ Error: {job_obj.error}")

        if events:
            click.echo("\nEvents:")
            event_list = client.list_events(job_id)
            for event in event_list:
                click.echo(f"  [{event['created_at']}] {event['message']}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@job.command("cancel")
@click.argument("job_id")
@click.confirmation_option(prompt="Are you sure you want to cancel this job?")
def job_cancel(job_id: str) -> None:
    """Cancel a fine-tuning job."""
    try:
        client = get_openai_client()
        job_obj = client.cancel_job(job_id)
        click.echo(f"Cancelled job: {job_obj.job_id}")
        click.echo(f"Status: {job_obj.status.value}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@job.command("events")
@click.argument("job_id")
@click.option("--limit", "-l", default=20, type=int, help="Maximum events to show")
def job_events(job_id: str, limit: int) -> None:
    """Show events for a fine-tuning job."""
    try:
        client = get_openai_client()
        events = client.list_events(job_id, limit=limit)

        if not events:
            click.echo("No events found.")
            return

        for event in events:
            level_color = {"error": "red", "warning": "yellow"}.get(event.get("level", ""), "white")
            click.echo(
                f"[{event['created_at']}] "
                f"{click.style(event['message'], fg=level_color)}"
            )

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Model Commands
# ============================================================================

@cli.group()
def model() -> None:
    """Manage fine-tuned models.

    View and evaluate your fine-tuned models trained with Midnighter.
    """
    pass


@model.command("list")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table")
def model_list(output_format: str) -> None:
    """List fine-tuned models."""
    try:
        client = get_openai_client()
        jobs = client.list_jobs(limit=100)

        # Filter to successful jobs with models
        models = [j for j in jobs if j.fine_tuned_model]

        if output_format == "json":
            click.echo(format_json([
                {"model_id": j.fine_tuned_model, "job_id": j.job_id, "tokens": j.trained_tokens}
                for j in models
            ]))
        else:
            if not models:
                click.echo("No fine-tuned models found.")
                return

            click.echo(f"\n{'Model ID':<50}  {'Tokens':<15}  {'Created':<20}")
            click.echo("-" * 90)
            for j in models:
                click.echo(
                    f"{j.fine_tuned_model[:50]:<50}  {j.trained_tokens:<15,}  "
                    f"{format_datetime(j.finished_at):<20}"
                )
            click.echo(f"\nTotal: {len(models)} models")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@model.command("evaluate")
@click.argument("model_id")
@click.option("--benchmark", "-b", default="behavior_adherence", help="Benchmark name")
@click.option("--sample-size", "-s", type=int, help="Sample size (default: all)")
@click.option("--output", "-o", type=click.Path(), help="Output results JSON")
def model_evaluate(
    model_id: str,
    benchmark: str,
    sample_size: Optional[int],
    output: Optional[str],
) -> None:
    """Evaluate a fine-tuned model on a benchmark."""
    try:
        eval_service = get_evaluation_service()

        click.echo(f"Evaluating model: {model_id}")
        click.echo(f"Benchmark: {benchmark}")
        if sample_size:
            click.echo(f"Sample size: {sample_size}")

        click.echo("\nRunning evaluation...")

        # Run async evaluation
        result = asyncio.run(
            eval_service.evaluate_model(
                model_id=model_id,
                benchmark=benchmark,
                sample_size=sample_size,
            )
        )

        click.echo(f"\n{'='*50}")
        click.echo("EVALUATION RESULTS")
        click.echo(f"{'='*50}")
        click.echo(f"Model: {result.model_id}")
        click.echo(f"Benchmark: {result.benchmark_name}")
        click.echo(f"Examples: {result.completed_examples}/{result.total_examples}")
        click.echo(f"Status: {result.status}")

        click.echo(f"\n{'Metrics':<30}  {'Value':<15}")
        click.echo("-" * 50)
        for metric, value in sorted(result.metrics.items()):
            if metric.endswith("_usd") or metric == "cost_usd":
                click.echo(f"{metric:<30}  ${value:.4f}")
            elif "rate" in metric or "adherence" in metric or "accuracy" in metric:
                click.echo(f"{metric:<30}  {value:.2%}")
            elif "latency" in metric:
                click.echo(f"{metric:<30}  {value:.3f}s")
            else:
                click.echo(f"{metric:<30}  {value}")

        if result.errors:
            click.echo(f"\n⚠ {len(result.errors)} errors occurred:")
            for error in result.errors[:5]:
                click.echo(f"  - {error}")

        if output:
            with open(output, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
            click.echo(f"\nResults saved to: {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@model.command("compare")
@click.argument("baseline_model")
@click.argument("candidate_model")
@click.option("--benchmark", "-b", default="behavior_adherence", help="Benchmark name")
@click.option("--sample-size", "-s", type=int, help="Sample size")
@click.option("--output", "-o", type=click.Path(), help="Output results JSON")
def model_compare(
    baseline_model: str,
    candidate_model: str,
    benchmark: str,
    sample_size: Optional[int],
    output: Optional[str],
) -> None:
    """Compare two models on a benchmark."""
    try:
        eval_service = get_evaluation_service()

        click.echo(f"Comparing models:")
        click.echo(f"  Baseline:  {baseline_model}")
        click.echo(f"  Candidate: {candidate_model}")
        click.echo(f"  Benchmark: {benchmark}")

        click.echo("\nRunning comparison...")

        result = asyncio.run(
            eval_service.compare_models(
                baseline_model=baseline_model,
                candidate_model=candidate_model,
                benchmark=benchmark,
                sample_size=sample_size,
            )
        )

        click.echo(f"\n{'='*60}")
        click.echo("COMPARISON RESULTS")
        click.echo(f"{'='*60}")

        winner_color = "green" if result.winner == "candidate" else "yellow"
        click.echo(f"Winner: {click.style(result.winner.upper(), fg=winner_color)}")
        click.echo(f"Confidence: {result.confidence:.0%}")

        click.echo(f"\n{'Metric':<25}  {'Baseline':<12}  {'Candidate':<12}  {'Δ':<12}")
        click.echo("-" * 60)

        for metric in ["behavior_adherence", "citation_accuracy", "hallucination_rate"]:
            base_val = result.baseline_metrics.get(metric, 0)
            cand_val = result.candidate_metrics.get(metric, 0)
            improvement = result.improvement.get(metric, 0)

            imp_str = f"{improvement:+.1%}" if improvement != 0 else "0%"
            imp_color = "green" if improvement > 0 else ("red" if improvement < 0 else "white")

            click.echo(
                f"{metric:<25}  {base_val:<12.2%}  {cand_val:<12.2%}  "
                f"{click.style(imp_str, fg=imp_color):<12}"
            )

        if output:
            with open(output, "w") as f:
                json.dump(result.to_dict(), f, indent=2)
            click.echo(f"\nResults saved to: {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Benchmark Commands
# ============================================================================

@cli.group()
def benchmark() -> None:
    """Manage evaluation benchmarks.

    Benchmarks are collections of test cases for evaluating model
    behavior adherence and quality.
    """
    pass


@benchmark.command("list")
def benchmark_list() -> None:
    """List available benchmarks."""
    try:
        eval_service = get_evaluation_service()
        benchmarks = eval_service.list_benchmarks()

        if not benchmarks:
            click.echo("No benchmarks found.")
            return

        click.echo("\nAvailable benchmarks:")
        for name in sorted(benchmarks):
            bench = eval_service.get_benchmark(name)
            if bench:
                click.echo(f"  • {name} ({len(bench.examples)} examples)")
            else:
                click.echo(f"  • {name}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@benchmark.command("generate")
@click.option("--from-agents-md", "-a", required=True, type=click.Path(exists=True),
              help="Path to AGENTS.md")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output JSON file")
@click.option("--examples-per-behavior", "-e", default=3, type=int, help="Examples per behavior")
def benchmark_generate(
    from_agents_md: str,
    output: str,
    examples_per_behavior: int,
) -> None:
    """Generate a benchmark from AGENTS.md."""
    try:
        from mdnt.evaluation import generate_benchmark_from_agents_md

        click.echo(f"Generating benchmark from {from_agents_md}...")

        bench = generate_benchmark_from_agents_md(
            agents_md_path=from_agents_md,
            examples_per_behavior=examples_per_behavior,
            output_path=output,
        )

        click.echo(f"\nGenerated benchmark: {bench.name}")
        click.echo(f"Examples: {len(bench.examples)}")
        click.echo(f"Output: {output}")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@benchmark.command("info")
@click.argument("name")
def benchmark_info(name: str) -> None:
    """Show details about a benchmark."""
    try:
        eval_service = get_evaluation_service()
        bench = eval_service.get_benchmark(name)

        if not bench:
            click.echo(f"Benchmark not found: {name}", err=True)
            sys.exit(1)

        click.echo(format_json(bench.to_dict()))

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# ============================================================================
# Config Command
# ============================================================================

@cli.command("config")
@click.option("--show", is_flag=True, help="Show current configuration")
def config_cmd(show: bool) -> None:
    """Show or manage configuration."""
    if show:
        click.echo("\nMidnighter Configuration:")
        click.echo("-" * 40)

        config = {
            "OPENAI_API_KEY": "***" + os.getenv("OPENAI_API_KEY", "")[-4:] if os.getenv("OPENAI_API_KEY") else "(not set)",
            "MDNT_OPENAI_MODEL": os.getenv("MDNT_OPENAI_MODEL", "gpt-4o-mini-2024-07-18"),
            "MDNT_OPENAI_SUFFIX": os.getenv("MDNT_OPENAI_SUFFIX", "mdnt-bcsft"),
            "MDNT_OPENAI_MAX_RETRIES": os.getenv("MDNT_OPENAI_MAX_RETRIES", "5"),
            "MDNT_OPENAI_RETRY_MIN_WAIT": os.getenv("MDNT_OPENAI_RETRY_MIN_WAIT", "1"),
            "MDNT_OPENAI_RETRY_MAX_WAIT": os.getenv("MDNT_OPENAI_RETRY_MAX_WAIT", "60"),
        }

        for key, value in config.items():
            click.echo(f"  {key}: {value}")
    else:
        click.echo("Use --show to display configuration")


# ============================================================================
# Entry Point
# ============================================================================

def main() -> int:
    """Main entry point for CLI."""
    try:
        cli()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
