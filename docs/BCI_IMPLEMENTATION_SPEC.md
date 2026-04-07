# Behavior-Conditioned Inference (BCI) Implementation Specification

## Mission

Implement the core Behavior-Conditioned Inference (BCI) pipeline from Meta's metacognitive reuse paper to achieve **46% token reduction** while maintaining or improving accuracy by retrieving and prepending relevant behaviors to prompts.

## Context

Per `Metacognitive_reuse.txt`, BCI is the primary mechanism that converts repeated reasoning patterns into token savings:

> "On MATH-500, BCI reduces reasoning tokens by up to 46% versus the same model without behaviors, while matching or improving accuracy."

Current state: Amprealize has a behavior handbook (`AGENTS.md` with 15+ behaviors) and BehaviorService storage, but lacks the retrieval and conditioning pipeline that delivers the token savings.

## Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Token reduction | 46% | Compare output tokens: BCI runs vs baseline runs on same tasks |
| Behavior reuse rate | 70% | % of runs that cite ≥1 behavior from handbook |
| Accuracy preservation | ≥100% | BCI accuracy / baseline accuracy on validation set |
| Retrieval latency | <100ms | P95 latency for Top-K retrieval + embedding |
| Citation compliance | 95% | % of BCI runs with parseable behavior citations in output |

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         BCI Pipeline                             │
└─────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  1. Query Analysis                                        │
    │     - Extract task keywords (topic, required reasoning)   │
    │     - Generate embedding for semantic search              │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  2. BehaviorRetriever                                     │
    │     - Hybrid retrieval: embedding similarity + keywords   │
    │     - Rank by relevance score                             │
    │     - Select Top-K behaviors (K=3-5 configurable)         │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  3. Prompt Composer                                       │
    │     - Format: "Relevant behaviors:\n- name: instruction"  │
    │     - Prepend to user query                               │
    │     - Add citation instruction                            │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  4. Model Inference                                       │
    │     - Pass conditioned prompt to LLM                      │
    │     - Model generates response with behavior citations    │
    └──────────────────────────────────────────────────────────┘
                                   │
                                   ▼
    ┌──────────────────────────────────────────────────────────┐
    │  5. Citation Parser & Validator                           │
    │     - Extract cited behavior names from output            │
    │     - Validate against prepended behaviors                │
    │     - Log to telemetry (fact_behavior_usage)              │
    └──────────────────────────────────────────────────────────┘
```

## Component 1: BehaviorRetriever

### Purpose
Retrieve the Top-K most relevant behaviors for a given query using hybrid retrieval (semantic + keyword matching).

### Implementation

#### Embedding Model Selection
- **Model**: BAAI/bge-m3 (BGE-M3)
- **Rationale**: Per Meta paper, BGE-M3 used for AIME embedding retrieval
- **Dimensions**: 1024 (multi-lingual, general-purpose)
- **Library**: `sentence-transformers>=2.0`

```python
from sentence_transformers import SentenceTransformer

class BehaviorRetriever:
    def __init__(self, behavior_service, model_name="BAAI/bge-m3"):
        self.behavior_service = behavior_service
        self.model = SentenceTransformer(model_name)
        self.index = None  # FAISS index, lazy-loaded
        self.behavior_ids = []  # Parallel array to index

    def initialize_index(self):
        """Build FAISS index from all behaviors in handbook."""
        behaviors = self.behavior_service.list_behaviors()
        texts = [f"{b['name']} {b['instruction']}" for b in behaviors]
        embeddings = self.model.encode(texts, convert_to_numpy=True)

        import faiss
        self.index = faiss.IndexFlatIP(embeddings.shape[1])  # Inner product for cosine similarity
        faiss.normalize_L2(embeddings)  # Normalize for cosine
        self.index.add(embeddings)
        self.behavior_ids = [b["id"] for b in behaviors]
```

#### Retrieval Strategies

1. **Embedding Similarity** (primary):
   - Encode query with same BGE-M3 model
   - FAISS nearest-neighbor search (cosine similarity)
   - Return Top-K by score

2. **Keyword Matching** (fallback for topic-based):
   - Extract task keywords (e.g., "math", "geometry", "inclusion-exclusion")
   - Match against behavior tags/categories
   - Used when embedding model unavailable or for MATH-500 topic-based retrieval

3. **Hybrid** (default):
   - Retrieve 2×K candidates via embedding
   - Re-rank using keyword overlap
   - Select Top-K from re-ranked list

```python
    def retrieve(self, query: str, top_k: int = 5, strategy: str = "hybrid") -> List[Dict]:
        """
        Retrieve Top-K behaviors for query.

        Args:
            query: User task description
            top_k: Number of behaviors to return (default 5)
            strategy: "embedding" | "keyword" | "hybrid" (default)

        Returns:
            List of behavior dicts with keys: id, name, instruction, score
        """
        if strategy == "embedding" or strategy == "hybrid":
            query_embedding = self.model.encode([query], convert_to_numpy=True)
            faiss.normalize_L2(query_embedding)

            k = top_k if strategy == "embedding" else 2 * top_k
            scores, indices = self.index.search(query_embedding, k)

            candidates = [
                {
                    **self.behavior_service.get_behavior(self.behavior_ids[idx]),
                    "score": float(scores[0][i])
                }
                for i, idx in enumerate(indices[0])
            ]

            if strategy == "hybrid":
                # Re-rank with keyword overlap
                candidates = self._rerank_with_keywords(query, candidates)
                candidates = candidates[:top_k]

        elif strategy == "keyword":
            # Topic-based matching (for MATH-500 compatibility)
            candidates = self._keyword_retrieve(query, top_k)

        return candidates
```

#### FAISS Index Management

- **Index Type**: `IndexFlatIP` (exact inner product search)
  - Justification: Small handbook size (<1000 behaviors), prioritize accuracy over speed
  - Future: Switch to `IndexIVFPQ` when handbook exceeds 10K behaviors

- **Persistence**: Store index alongside SQLite DB
  - File: `behaviors.faiss` (binary index), `behavior_ids.json` (ID mapping)
  - Rebuild trigger: After behavior create/update/delete

- **Updates**: Incremental re-indexing
  - New behavior → encode → add to index → persist
  - Updated behavior → remove old vector → add new vector
  - Deleted behavior → compact index (rebuild if >10% deleted)

### RBAC Integration

- **Scope**: `retrieval.read` (implicit for all authenticated users)
- **Rate Limiting**: 100 queries per minute per user
- **Audit**: Log query, top_k, strategy, retrieved behavior IDs to `telemetry_retrieval_query` event

## Component 2: Prompt Composer

### Purpose
Format retrieved behaviors into a structured prompt prefix that guides model reasoning.

### Prompt Template

```python
def compose_bci_prompt(behaviors: List[Dict], user_query: str) -> str:
    """
    Compose behavior-conditioned prompt.

    Format per Meta paper:
        Relevant behaviors:
        - behavior_name_1: instruction text
        - behavior_name_2: instruction text

        Please reference these behaviors explicitly when applicable.

        Now solve: {user_query}
    """
    if not behaviors:
        return user_query  # Fallback to unconditioned prompt

    behavior_lines = [
        f"- {b['name']}: {b['instruction']}"
        for b in behaviors
    ]
    behavior_block = "\n".join(behavior_lines)

    prompt = f"""Relevant behaviors:
{behavior_block}

Please reference these behaviors explicitly (by name) when they apply to your reasoning.

Now solve: {user_query}"""

    return prompt
```

### Design Notes

1. **Citation Instruction**: Critical for parseable output. Model must emit `behavior_name` when using a behavior.

2. **Token Budget**: Behaviors consume input tokens (pre-computable, often cheaper than output tokens per Meta paper). Average behavior: ~20-40 tokens. Top-5 behaviors: ~150 input tokens overhead.

3. **Ordering**: Present behaviors in relevance rank order (highest score first) to focus model attention.

4. **Extensibility**: Template supports adding examples or constraints per behavior in future phases.

## Component 3: Citation Parser & Validator

### Purpose
Extract behavior references from model output, validate citations, and log usage for telemetry.

### Implementation

```python
import re
from typing import List, Set

class CitationParser:
    def __init__(self, behavior_service):
        self.behavior_service = behavior_service

    def parse_citations(self, model_output: str, prepended_behaviors: List[str]) -> Dict:
        """
        Extract behavior citations from model output.

        Args:
            model_output: Raw LLM response text
            prepended_behaviors: List of behavior names that were prepended

        Returns:
            {
                "cited_behaviors": ["behavior_name_1", ...],
                "valid_citations": ["behavior_name_1", ...],  # subset of cited that were prepended
                "invalid_citations": ["behavior_unknown", ...],  # cited but not prepended
                "compliance": float,  # valid_citations / prepended_behaviors
            }
        """
        # Pattern: match "behavior_*" or "`behavior_*`" in output
        pattern = r'`?(behavior_[a-z_]+)`?'
        matches = re.findall(pattern, model_output, re.IGNORECASE)

        cited_behaviors = list(set(matches))  # Deduplicate
        prepended_set = set(prepended_behaviors)

        valid_citations = [b for b in cited_behaviors if b in prepended_set]
        invalid_citations = [b for b in cited_behaviors if b not in prepended_set]

        compliance = len(valid_citations) / len(prepended_set) if prepended_set else 0.0

        return {
            "cited_behaviors": cited_behaviors,
            "valid_citations": valid_citations,
            "invalid_citations": invalid_citations,
            "compliance": compliance,
        }
```

### Validation Rules

1. **Minimum Citation Requirement**: BCI runs should cite ≥1 behavior. If zero citations, log warning but don't fail run.

2. **Invalid Citation Handling**: If model hallucinates behavior names, log to telemetry for reflection analysis (may indicate missing behaviors).

3. **Partial Compliance**: Acceptable if model cites subset of prepended behaviors (not all may be relevant).

### Telemetry Integration

After parsing, emit event:

```json
{
  "event_type": "telemetry.bci.citation_validation",
  "timestamp": "2025-10-16T10:30:00Z",
  "run_id": "run_abc123",
  "prepended_behaviors": ["behavior_inclusion_exclusion_principle", "behavior_distance_from_point_to_line"],
  "cited_behaviors": ["behavior_inclusion_exclusion_principle"],
  "valid_citations": ["behavior_inclusion_exclusion_principle"],
  "invalid_citations": [],
  "compliance": 0.5,
  "metadata": {
    "retrieval_strategy": "hybrid",
    "top_k": 5,
    "retrieval_scores": [0.89, 0.76, ...]
  }
}
```

This feeds `fact_behavior_usage` table for calculating 70% reuse rate KPI.

## Component 4: Telemetry Integration

### Purpose
Track BCI pipeline execution to measure success criteria and identify optimization opportunities.

### Key Metrics

1. **Token Reduction**:
   - Baseline: Run same task without BCI → measure output tokens
   - BCI: Run with BCI → measure output tokens
   - Reduction = (baseline - bci) / baseline × 100%

2. **Behavior Reuse Rate**:
   - Total runs with ≥1 cited behavior / total BCI runs
   - Target: 70%

3. **Retrieval Performance**:
   - Latency: Time from query to retrieved behaviors
   - Relevance: Manual eval of Top-K behaviors (sample 100 runs)
   - Index size: Number of behaviors indexed

4. **Citation Compliance**:
   - Valid citations / prepended behaviors per run
   - Tracks model adherence to citation instruction

### Event Schema

See `contracts/TELEMETRY_SCHEMA.md` for full schema. BCI-specific events:

- `telemetry.bci.retrieval_start` → query, top_k, strategy
- `telemetry.bci.retrieval_complete` → behavior_ids, scores, latency_ms
- `telemetry.bci.prompt_composed` → prepended_behaviors, input_tokens
- `telemetry.bci.citation_validation` → cited_behaviors, compliance

### Dashboard Visualizations

Coordinate with Analytics for dashboard updates (per `PRD_NEXT_STEPS.md`):

1. **Token Savings Chart**: Line graph showing cumulative token reduction over time
2. **Behavior Reuse Heatmap**: Grid showing which behaviors cited most frequently
3. **Retrieval Quality**: Scatter plot of relevance scores vs citation compliance
4. **A/B Test Results**: BCI vs baseline accuracy and token comparison

## Integration Points

### RunService Integration

Update `amprealize/workflow_service.py` to inject BCI pipeline:

```python
class WorkflowService:
    def __init__(self, behavior_service, retriever: BehaviorRetriever):
        self.behavior_service = behavior_service
        self.retriever = retriever
        self.citation_parser = CitationParser(behavior_service)

    def run_with_bci(self, query: str, top_k: int = 5) -> Dict:
        """Execute workflow with BCI conditioning."""
        # 1. Retrieve behaviors
        behaviors = self.retriever.retrieve(query, top_k=top_k)

        # 2. Compose prompt
        conditioned_prompt = compose_bci_prompt(behaviors, query)

        # 3. Call LLM (placeholder - wire to actual model inference)
        model_output = self._call_llm(conditioned_prompt)

        # 4. Parse citations
        citation_result = self.citation_parser.parse_citations(
            model_output,
            [b["name"] for b in behaviors]
        )

        # 5. Log telemetry
        self._log_bci_run(query, behaviors, citation_result, model_output)

        return {
            "output": model_output,
            "behaviors_used": citation_result["valid_citations"],
            "compliance": citation_result["compliance"],
        }
```

### CLI Integration

Add `amprealize run --bci` flag:

```bash
$ amprealize run --bci "Solve: How many ways to arrange 5 books on a shelf?"
Retrieving behaviors... (5 found)
Running with BCI conditioning...
Output: Using behavior_permutation_formula...
Behaviors cited: behavior_permutation_formula (1/5 prepended)
Compliance: 20%
```

### MCP Tool Integration

Create `mcp/tools/bci.retrieve.json`:

```json
{
  "name": "bci.retrieve",
  "description": "Retrieve Top-K behaviors for a query using BCI pipeline",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Task description"},
      "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
      "strategy": {"type": "string", "enum": ["embedding", "keyword", "hybrid"], "default": "hybrid"}
    },
    "required": ["query"]
  }
}
```

## Dependencies

### Python Packages

```txt
sentence-transformers>=2.0.0  # BGE-M3 model
faiss-cpu>=1.7.0             # FAISS index (or faiss-gpu for production)
numpy>=1.21.0                # Array operations
torch>=2.0.0                 # PyTorch backend for sentence-transformers
```

### Model Download

First run will download BGE-M3 (~2GB):

```python
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("BAAI/bge-m3")  # Auto-downloads to ~/.cache/torch/sentence_transformers/
```

### Storage Requirements

- BGE-M3 model: ~2GB disk
- FAISS index: ~4MB per 1000 behaviors (1024-dim float32 vectors)
- For 100 behaviors: ~400KB index size

## Implementation Phases

### Phase 1: Core BCI Pipeline (Week 1-2)

- [ ] Install dependencies (sentence-transformers, faiss-cpu)
- [ ] Implement `BehaviorRetriever` class with embedding + FAISS index
- [ ] Implement `compose_bci_prompt` function
- [ ] Implement `CitationParser` class
- [ ] Wire BCI pipeline into `WorkflowService.run_with_bci()`
- [ ] Add telemetry events for retrieval, composition, citation validation
- [ ] Unit tests for each component

### Phase 2: CLI & MCP Integration (Week 2)

- [ ] Add `amprealize run --bci` CLI flag
- [ ] Create MCP tool `bci.retrieve.json`
- [ ] Add `amprealize behaviors index` CLI command to rebuild FAISS index
- [ ] Integration tests for CLI/MCP parity

### Phase 3: Validation & Optimization (Week 2)

- [ ] A/B test framework: BCI vs baseline prompts
- [ ] Collect 100+ runs, measure token reduction
- [ ] Validate 46% token savings target
- [ ] Tune Top-K parameter (test K=3,5,7,10)
- [ ] Optimize retrieval latency (<100ms P95)

### Phase 4: Dashboard & Reporting (Week 3)

- [ ] Wire telemetry to DuckDB warehouse `fact_behavior_usage` table
- [ ] Create dashboard visualizations (token savings, reuse rate, compliance)
- [ ] Export BCI metrics API endpoint for programmatic access

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| BGE-M3 model download failures | High (blocking) | Cache model in Docker image, fallback to keyword retrieval |
| FAISS index corruption | Medium (retrieval broken) | Auto-rebuild on startup if index missing/invalid, daily backup |
| Low citation compliance (<95%) | Medium (telemetry gaps) | Improve citation instruction prompt, add few-shot examples |
| Retrieval latency >100ms | Low (UX degraded) | Upgrade to FAISS IVF index, move to GPU, cache Top-K for common queries |
| Token savings <46% target | High (core value prop) | Tune Top-K, improve behavior quality, analyze underperforming behaviors |

## Validation Checklist

Before marking BCI implementation complete, confirm:

- [ ] **Token Reduction**: Measured ≥40% reduction on 100+ test runs (targeting 46%)
- [ ] **Behavior Reuse**: ≥70% of BCI runs cite ≥1 behavior
- [ ] **Accuracy**: BCI accuracy ≥ baseline accuracy on validation set
- [ ] **Retrieval Latency**: P95 latency <100ms for Top-5 retrieval
- [ ] **Citation Compliance**: ≥95% of runs have parseable citations
- [ ] **Index Integrity**: FAISS index rebuilds successfully after behavior CRUD operations
- [ ] **Telemetry**: All BCI events flowing to DuckDB warehouse
- [ ] **Parity**: BCI available via CLI (`amprealize run --bci`) and MCP (`bci.retrieve`)
- [ ] **Documentation**: User guide, API reference, troubleshooting runbook published

## References

- **Meta Paper**: `Metacognitive_reuse.txt` (full paper text)
- **Behavior Handbook**: `AGENTS.md` (existing behaviors)
- **BehaviorService**: `amprealize/behavior_service.py` (storage layer)
- **Telemetry Schema**: `contracts/TELEMETRY_SCHEMA.md` (event definitions)
- **PRD Success Metrics**: `PRD.md` §§3.2 (70% reuse, 30% token savings targets)

---

**Status**: ✅ Specification Complete
**Owner**: Engineering
**Dependencies**: sentence-transformers, faiss-cpu, BGE-M3 model
**Next**: Update `PRD.md` to integrate BCI into Milestone 2 scope
**Last Updated**: 2025-10-16
