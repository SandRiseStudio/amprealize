# Midnighter (mdnt)

> Behavior-Conditioned Supervised Fine-Tuning (BC-SFT) library for training LLMs with procedural knowledge.

Midnighter implements the BC-SFT methodology from [Meta's Metacognitive Reuse research](https://arxiv.org/pdf/2509.13237), enabling you to compress repeated reasoning patterns into reusable "behaviors" and fine-tune models to apply them automatically.

## Features

- 🎯 **Behavior-Conditioned Training**: Generate training examples that teach LLMs to follow procedural guidelines
- 🚀 **Multiple Backends**: OpenAI Fine-Tuning API (managed) or local PyTorch/Transformers (experimental)
- 📊 **Quality Scoring**: Automatic quality assessment for generated training examples
- 🔌 **Hooks Architecture**: Zero-dependency core with hooks for integration into any system
- 🌐 **FastAPI Routes**: Ready-to-use REST API for training pipeline management

## Installation

```bash
# Core only (no training backends)
pip install midnighter

# With OpenAI Fine-Tuning API (recommended)
pip install midnighter[openai]

# With local PyTorch training (experimental, requires GPU)
pip install midnighter[local]

# With FastAPI routes
pip install midnighter[fastapi]

# Everything
pip install midnighter[all]
```

## Quick Start

### Using OpenAI Backend (Recommended)

```python
from mdnt import MidnighterService, MidnighterHooks
from mdnt.clients.openai import OpenAIFineTuningClient

# Initialize service with hooks
service = MidnighterService(
    hooks=MidnighterHooks(
        # Provide your behavior retrieval function
        get_behavior=lambda id: your_behavior_store.get(id),
        # Optional: telemetry callback
        on_metric=lambda event, data: print(f"Metric: {event}"),
    ),
    backend="openai"
)

# Generate training corpus from behaviors
corpus = service.generate_corpus_from_behaviors(
    name="my-behavior-corpus",
    description="Training examples for code review behaviors",
    behavior_ids=["behavior_code_review", "behavior_test_coverage"],
    sample_count=100
)

# Start fine-tuning job
job = service.start_training_job(
    model_id="my-finetuned-model",
    base_model="gpt-4o-mini",
    corpus_id=corpus.corpus_id,
    config={"epochs": 3}
)

# Check status
status = service.get_job(job.job_id)
print(f"Status: {status.status}, Progress: {status.progress}")
```

### Using Local Backend (Experimental)

```python
from mdnt import MidnighterService

# Requires: pip install midnighter[local]
service = MidnighterService(backend="local")

# Same API as OpenAI backend
job = service.start_training_job(
    model_id="my-local-model",
    base_model="llama-3.1-8b",  # Hugging Face model ID
    corpus_id=corpus.corpus_id,
    config={
        "epochs": 3,
        "batch_size": 4,
        "learning_rate": 2e-5,
        "use_lora": True,  # Recommended for efficiency
        "lora_r": 16,
    }
)
```

## Architecture

Midnighter follows a hooks-based architecture for maximum flexibility:

```
┌─────────────────────────────────────────────────────────┐
│                   MidnighterService                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐  │
│  │   Corpus    │  │   Training  │  │    Evaluation   │  │
│  │  Generator  │  │   Manager   │  │     Manager     │  │
│  └──────┬──────┘  └──────┬──────┘  └────────┬────────┘  │
│         │                │                   │          │
│         └────────────────┼───────────────────┘          │
│                          │                              │
│                   MidnighterHooks                       │
│         (get_behavior, on_metric, on_action, etc.)      │
└──────────────────────────┼──────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
     ┌──────▼─────┐ ┌──────▼─────┐ ┌──────▼─────┐
     │   OpenAI   │ │   Local    │ │  Custom    │
     │   Client   │ │  Trainer   │ │  Backend   │
     └────────────┘ └────────────┘ └────────────┘
```

## Hooks Reference

```python
from mdnt import MidnighterHooks
from typing import Dict, Any, List, Optional

hooks = MidnighterHooks(
    # Required: Retrieve a behavior by ID
    get_behavior=lambda behavior_id: {...},

    # Optional: Retrieve multiple behaviors for a query
    retrieve_behaviors=lambda query, top_k: [...],

    # Optional: Called when training actions occur
    on_action=lambda action_type, payload: None,

    # Optional: Called for telemetry/metrics
    on_metric=lambda event_type, data: None,

    # Optional: Called during compliance checks
    on_compliance_step=lambda step, result: None,
)
```

## FastAPI Integration

```python
from fastapi import FastAPI
from mdnt.fastapi import create_midnighter_routes

app = FastAPI()

# Mount midnighter routes
routes = create_midnighter_routes(
    prefix="/v1/training",
    hooks=your_hooks,
)
app.include_router(routes)

# Available endpoints:
# POST /v1/training/corpora - Create training corpus
# GET  /v1/training/corpora - List corpora
# GET  /v1/training/corpora/{id} - Get corpus details
# POST /v1/training/jobs - Start training job
# GET  /v1/training/jobs - List jobs
# GET  /v1/training/jobs/{id} - Get job status
# POST /v1/training/jobs/{id}/cancel - Cancel job
# GET  /v1/training/models - List fine-tuned models
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key (required for openai backend) | - |
| `MDNT_BACKEND` | Training backend: "openai" or "local" | "openai" |
| `MDNT_OPENAI_MODEL` | Base model for OpenAI fine-tuning | "gpt-4o-mini-2024-07-18" |
| `MDNT_OPENAI_SUFFIX` | Suffix for fine-tuned model names | "mdnt-bcsft" |
| `MDNT_MODELS_DIR` | Directory for local model checkpoints | "./models" |
| `MDNT_USE_LLM_EXAMPLES` | Use LLM for example generation | "true" |
| `MDNT_TEACHER_MODEL` | Model for Teacher role example generation | "gpt-4o-mini" |
| `SLACK_WEBHOOK_URL` | Slack webhook for cost alerts (optional) | - |

## CLI Reference

Midnighter provides a full CLI for managing training pipelines:

```bash
# Install CLI
pip install midnighter[cli]

# Corpus Management
mdnt corpus list                           # List all corpora
mdnt corpus create NAME --behaviors b1,b2  # Create from behaviors
mdnt corpus generate NAME --behaviors b1   # Generate with LLM examples
mdnt corpus export CORPUS_ID --format jsonl
mdnt corpus delete CORPUS_ID

# Job Management
mdnt job start CORPUS_ID                   # Start training job
mdnt job list                              # List all jobs
mdnt job status JOB_ID                     # Check status
mdnt job cancel JOB_ID                     # Cancel running job
mdnt job events JOB_ID                     # View job events

# Model Management
mdnt model list                            # List fine-tuned models
mdnt model register MODEL_ID --name "My Model"

# Evaluation
mdnt evaluate run MODEL_ID --benchmark benchmarks/eval.jsonl
mdnt evaluate compare MODEL_1 MODEL_2 --benchmark benchmarks/eval.jsonl
```

### CLI Output Formats

```bash
# Table output (default)
mdnt job list

# JSON output for scripting
mdnt job list --format json | jq '.[] | select(.status == "running")'
```

## Evaluation Pipeline

Midnighter includes an automated evaluation pipeline for comparing model performance:

```python
from mdnt.evaluation import EvaluationService, BenchmarkConfig

# Configure evaluation
config = BenchmarkConfig(
    benchmark_path="benchmarks/evaluation_benchmark.jsonl",
    metrics=["behavior_adherence", "response_quality", "hallucination_score"],
    parallel_workers=4,
)

# Run evaluation
eval_service = EvaluationService(openai_client=client)
results = await eval_service.run_benchmark(
    model_id="ft:gpt-4o-mini:org::abc123",
    config=config,
)

print(f"Behavior Adherence: {results.behavior_adherence_score:.2%}")
print(f"Response Quality: {results.response_quality_score:.2%}")
print(f"Hallucination Score: {results.hallucination_score:.2%}")

# Compare models
comparison = await eval_service.compare_models(
    model_a="ft:gpt-4o-mini:org::abc123",
    model_b="gpt-4o-mini",  # baseline
    config=config,
)
```

### Generating Benchmarks from AGENTS.md

```bash
# Generate benchmark dataset from behavior definitions
python scripts/generate_benchmark.py \
    --agents-md /path/to/AGENTS.md \
    --output benchmarks/

# Output:
# - benchmarks/evaluation_benchmark.jsonl (123 test cases)
# - benchmarks/benchmark_summary.json (statistics)
# - benchmarks/behaviors.json (extracted behaviors)
```

## Cost Optimization Strategies

### 1. Model Selection

| Model | Training Cost | Inference Cost | Best For |
|-------|--------------|----------------|----------|
| `gpt-4o-mini-2024-07-18` | ~$0.003/1K tokens | ~$0.00015/1K | General BC-SFT, budget-friendly |
| `gpt-4o-2024-08-06` | ~$0.025/1K tokens | ~$0.0025/1K | Complex behaviors, high quality |

**Recommendation**: Start with `gpt-4o-mini` for initial experiments, upgrade to `gpt-4o` only for production models with complex behaviors.

### 2. Corpus Optimization

```python
# Optimal corpus sizes
# - Minimum: 50 examples per behavior (baseline quality)
# - Recommended: 100-200 examples per behavior (good quality)
# - Maximum: 500 examples per behavior (diminishing returns)

# Quality over quantity: High-quality examples matter more
corpus = service.generate_corpus_from_behaviors(
    behavior_ids=behaviors,
    sample_count=150,  # Sweet spot for cost/quality
    quality_threshold=0.8,  # Filter low-quality examples
)
```

### 3. Training Configuration

```python
# Cost-effective defaults
job = service.start_training_job(
    base_model="gpt-4o-mini-2024-07-18",
    config={
        "epochs": 3,  # 2-4 is usually sufficient
        "batch_size": 4,  # Higher = more efficient
        "learning_rate_multiplier": 1.8,  # Default is fine
    }
)
```

### 4. Cost Monitoring & Alerts

```python
from mdnt.integrations import create_raze_hooks

# Set up cost alerting with Slack
hooks = create_raze_hooks(
    slack_webhook_url="https://hooks.slack.com/services/XXX",
    slack_channel="#ml-costs",
    cost_threshold_usd=50.0,  # Alert when cost exceeds $50
)

service = MidnighterService(hooks=hooks)
```

### 5. Estimated Costs by Use Case

| Use Case | Corpus Size | Training Cost | Monthly Inference |
|----------|-------------|---------------|-------------------|
| Single behavior, POC | 100 examples | ~$0.30 | ~$5-10 |
| 5 behaviors, MVP | 500 examples | ~$1.50 | ~$25-50 |
| Full handbook (20+ behaviors) | 2,000 examples | ~$6.00 | ~$100-200 |

### 6. Cost Reduction Checklist

- [ ] Use `gpt-4o-mini` for development/testing
- [ ] Set quality thresholds to filter poor examples
- [ ] Limit epochs to 3-4 (check loss curves)
- [ ] Enable cost alerts via Raze integration
- [ ] Review training data for duplicates
- [ ] Use batch inference for evaluation
- [ ] Cache embeddings for behavior retrieval

## Raze Integration

Midnighter integrates with [Raze](../raze/) for structured logging and cost tracking:

```python
from mdnt.integrations import create_raze_hooks, RazeCostTracker

# Option 1: Quick setup with hooks factory
hooks = create_raze_hooks(
    slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
    cost_threshold_usd=25.0,
)

# Option 2: Manual cost tracker for more control
tracker = RazeCostTracker(
    slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
    cost_threshold_usd=25.0,
    source="my-training-pipeline",
)

# Get cost summary
summary = tracker.get_summary()
print(f"Total cost: ${summary['total_cost_usd']:.2f}")
print(f"By model: {summary['by_model']}")
```

## Production Deployment

See [DEPLOYMENT_CHECKLIST.md](./DEPLOYMENT_CHECKLIST.md) for a complete production readiness checklist.

Quick checklist:
- [ ] Set `OPENAI_API_KEY` via secrets manager
- [ ] Configure cost alerts with Slack webhook
- [ ] Set up rate limiting for API endpoints
- [ ] Enable structured logging with Raze
- [ ] Create backup/rollback procedures for fine-tuned models
- [ ] Set up monitoring dashboards

## Research Background

Midnighter implements the BC-SFT methodology from Meta AI's "Metacognitive Reuse" research:

> **Meta AI Proposes 'Metacognitive Reuse': Turning LLM Chains-of-Thought into a Procedural Handbook that Cuts Tokens by 46%**
>
> The method compresses repeated reasoning patterns into short, named procedures—"behaviors"—and then conditions models to use them at inference or distills them via fine-tuning.
>
> Results: Up to 46% fewer reasoning tokens on MATH while matching or improving accuracy.

[Read the full paper](https://arxiv.org/pdf/2509.13237)

## License

MIT License - see [LICENSE](LICENSE) for details.
