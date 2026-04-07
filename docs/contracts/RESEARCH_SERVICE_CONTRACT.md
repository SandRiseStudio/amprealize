# Research Service Contract

> **Status**: Draft
> **Version**: 1.0.0
> **Last Updated**: 2025-01-20
> **Owner**: AI Research Agent

---

## 1. Purpose

The Research Service provides a **standardized, automated pipeline** for evaluating AI research papers and articles for potential integration into Amprealize. It transforms ad-hoc research review into a repeatable process with consistent output format, honest evaluation criteria, and actionable implementation recommendations.

### Goals

1. **Comprehension**: Deep analysis of research papers (URL, markdown, PDF) extracting key ideas, technical approaches, and claimed results
2. **Evaluation**: LLM-driven scoring with structured output assessing fit, feasibility, and value for Amprealize
3. **Recommendation**: Clear verdicts (ADOPT/ADAPT/DEFER/REJECT) with implementation roadmaps when appropriate
4. **Reproducibility**: Every evaluation produces identical output format, enabling comparison across papers

### Non-Goals

- Real-time paper monitoring/alerting (future consideration)
- Automatic implementation of research ideas (handoff to other agents)
- Academic paper writing or submission

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Research Evaluation Pipeline                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │   INGEST     │ →  │  COMPREHEND  │ →  │   EVALUATE   │ →  │ RECOMMEND │ │
│  │              │    │              │    │              │    │           │ │
│  │ • URL fetch  │    │ • Key ideas  │    │ • Fit score  │    │ • Verdict │ │
│  │ • PDF parse  │    │ • Tech summ  │    │ • Feasibility│    │ • Roadmap │ │
│  │ • MD read    │    │ • Novelty    │    │ • Conflicts  │    │ • Handoff │ │
│  │ • Normalize  │    │ • Claims     │    │ • Resources  │    │           │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│         │                   │                   │                   │       │
│         ▼                   ▼                   ▼                   ▼       │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         Storage Layer                                 │  │
│  │   SQLite (MVP) → PostgreSQL (Production)                             │  │
│  │   Tables: papers, evaluations, roadmaps                              │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
              ┌──────────┐     ┌──────────┐     ┌──────────┐
              │   CLI    │     │   MCP    │     │   API    │
              │ research │     │ research │     │/v1/research│
              │ evaluate │     │   .*     │     │          │
              └──────────┘     └──────────┘     └──────────┘
```

---

## 3. Pipeline Phases

### Phase 1: Ingest

**Purpose**: Accept research content from multiple sources and normalize to processable text.

| Input Type | Handler | Library | Notes |
|------------|---------|---------|-------|
| URL (arxiv, blog, etc.) | `WebIngester` | `httpx` + `beautifulsoup4` | Extracts main content, strips nav/ads |
| URL (arxiv PDF) | `ArxivIngester` | `arxiv` API | Fetches metadata + PDF, extracts text |
| Markdown file | `MarkdownIngester` | Built-in | Direct read, preserves structure |
| PDF file | `PDFIngester` | `pymupdf` (fitz) | Extracts text with layout awareness |
| DOCX file | `DocxIngester` | `python-docx` | Future consideration |

**Output**: `IngestedPaper` dataclass with:
- `raw_text`: Full extracted text
- `metadata`: Title, authors, date, source URL, arxiv ID (if applicable)
- `sections`: Parsed sections (abstract, introduction, methods, results, etc.)
- `figures_tables`: Extracted figure/table captions (text only for MVP)

### Phase 2: Comprehend

**Purpose**: LLM-driven deep analysis producing structured understanding of the research.

**LLM Prompt Strategy**: Single comprehensive prompt with structured JSON output.

**Output**: `ComprehensionResult` dataclass with:

```python
@dataclass
class ComprehensionResult:
    # Core Understanding
    core_idea: str                    # 2-3 sentence summary
    problem_addressed: str            # What problem does this solve?
    proposed_solution: str            # How do they solve it?

    # Technical Details
    key_contributions: list[str]      # Bullet list of novel contributions
    technical_approach: str           # How it works (1-2 paragraphs)
    algorithms_methods: list[str]     # Named algorithms, architectures

    # Claims & Results
    claimed_results: list[ClaimedResult]  # Metric, improvement, conditions
    benchmarks_used: list[str]        # Datasets, benchmarks evaluated on
    limitations_acknowledged: list[str]  # Self-reported limitations

    # Novelty Assessment
    novelty_score: float              # 1-10, LLM-assessed
    novelty_rationale: str            # Why this score?
    related_work_summary: str         # How does it compare to prior art?

    # Metadata
    comprehension_confidence: float   # 0-1, how confident is the LLM?
    key_terms: list[str]              # Important technical terms
```

### Phase 3: Evaluate

**Purpose**: Honest assessment of whether Amprealize should adopt this research.

**Evaluation Criteria** (from AGENT_AI_RESEARCH.md playbook):

| Criterion | Weight | Description |
|-----------|--------|-------------|
| **Relevance** | 0.25 | How applicable to Amprealize's mission and architecture? |
| **Feasibility** | 0.25 | Can we realistically implement with current resources? |
| **Novelty** | 0.20 | Does this offer something we don't already have? |
| **ROI** | 0.20 | Is benefit worth implementation + maintenance cost? |
| **Safety** | 0.10 | Any alignment, security, or reliability concerns? |

**Context Documents Provided to LLM**:
- `AGENTS.md` (existing behaviors and patterns)
- `PRD.md` (product requirements and roadmap)
- `MCP_SERVER_DESIGN.md` (current architecture)
- `WORK_STRUCTURE.md` (resource constraints)

**Output**: `EvaluationResult` dataclass with:

```python
@dataclass
class EvaluationResult:
    # Scores (1-10 each)
    relevance_score: float
    relevance_rationale: str

    feasibility_score: float
    feasibility_rationale: str

    novelty_score: float
    novelty_rationale: str

    roi_score: float
    roi_rationale: str

    safety_score: float
    safety_rationale: str

    # Weighted overall
    overall_score: float              # Weighted combination

    # Conflict Detection
    conflicts_with_existing: list[ConflictItem]  # behavior_name, description

    # Resource Assessment
    implementation_complexity: Complexity  # LOW, MEDIUM, HIGH, VERY_HIGH
    maintenance_burden: Complexity
    expertise_gap: Complexity
    estimated_effort: str             # T-shirt size + justification

    # Honest Concerns
    concerns: list[str]               # Bullet list of worries
    risks: list[str]                  # What could go wrong?

    # Benefits
    potential_benefits: list[str]     # What we'd gain
```

### Phase 4: Recommend

**Purpose**: Final verdict with actionable next steps.

**Verdict Logic**:

```python
def calculate_verdict(overall_score: float, conflicts: list, safety_score: float) -> Verdict:
    # Safety veto
    if safety_score < 4.0:
        return Verdict.REJECT

    # Conflict handling
    if len(conflicts) > 2 and overall_score < 8.0:
        return Verdict.DEFER

    # Score-based
    if overall_score >= 7.5:
        return Verdict.ADOPT
    elif overall_score >= 5.5:
        return Verdict.ADAPT
    elif overall_score >= 3.5:
        return Verdict.DEFER
    else:
        return Verdict.REJECT
```

| Verdict | Meaning | Action |
|---------|---------|--------|
| **ADOPT** | Implement as described | Generate full implementation roadmap |
| **ADAPT** | Implement with modifications | Generate adapted roadmap with changes |
| **DEFER** | Interesting but not now | Document for future consideration |
| **REJECT** | Not suitable for Amprealize | Document rationale, no roadmap |

**Output**: `Recommendation` dataclass with:

```python
@dataclass
class Recommendation:
    verdict: Verdict                  # ADOPT, ADAPT, DEFER, REJECT
    verdict_rationale: str            # 2-3 sentences explaining decision

    # Only if ADOPT or ADAPT
    implementation_roadmap: Optional[ImplementationRoadmap]

    # Handoff
    next_agent: Optional[str]         # architect, engineering, etc.
    priority: Priority                # P1, P2, P3, P4
    blocking_dependencies: list[str]  # What must happen first?

@dataclass
class ImplementationRoadmap:
    affected_components: list[AffectedComponent]  # path, what_changes
    proposed_steps: list[ImplementationStep]      # ordered steps
    success_criteria: list[str]                   # measurable outcomes
    estimated_effort: str                         # T-shirt + justification

    # If ADAPT
    adaptations_needed: list[str]     # What we're changing from original
```

---

## 4. Data Schemas

### 4.1 Database Tables (SQLite MVP)

```sql
-- Research papers ingested into the system
CREATE TABLE research_papers (
    id TEXT PRIMARY KEY,              -- UUID
    title TEXT NOT NULL,
    authors TEXT,                     -- JSON array
    source_url TEXT,
    source_type TEXT NOT NULL,        -- 'url', 'arxiv', 'markdown', 'pdf'
    arxiv_id TEXT,
    publication_date TEXT,
    raw_text TEXT NOT NULL,
    sections TEXT,                    -- JSON object
    metadata TEXT,                    -- JSON object
    created_at TEXT NOT NULL,
    created_by TEXT
);

-- Comprehension results
CREATE TABLE comprehensions (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES research_papers(id),
    core_idea TEXT NOT NULL,
    problem_addressed TEXT,
    proposed_solution TEXT,
    key_contributions TEXT,           -- JSON array
    technical_approach TEXT,
    claimed_results TEXT,             -- JSON array
    novelty_score REAL,
    novelty_rationale TEXT,
    comprehension_confidence REAL,
    key_terms TEXT,                   -- JSON array
    llm_model TEXT,
    created_at TEXT NOT NULL
);

-- Evaluation results
CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES research_papers(id),
    comprehension_id TEXT NOT NULL REFERENCES comprehensions(id),

    relevance_score REAL,
    relevance_rationale TEXT,
    feasibility_score REAL,
    feasibility_rationale TEXT,
    novelty_score REAL,
    novelty_rationale TEXT,
    roi_score REAL,
    roi_rationale TEXT,
    safety_score REAL,
    safety_rationale TEXT,

    overall_score REAL,
    conflicts TEXT,                   -- JSON array
    implementation_complexity TEXT,
    maintenance_burden TEXT,
    expertise_gap TEXT,
    estimated_effort TEXT,
    concerns TEXT,                    -- JSON array
    risks TEXT,                       -- JSON array
    potential_benefits TEXT,          -- JSON array

    llm_model TEXT,
    created_at TEXT NOT NULL
);

-- Final recommendations
CREATE TABLE recommendations (
    id TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL REFERENCES research_papers(id),
    evaluation_id TEXT NOT NULL REFERENCES evaluations(id),

    verdict TEXT NOT NULL,            -- ADOPT, ADAPT, DEFER, REJECT
    verdict_rationale TEXT,

    implementation_roadmap TEXT,      -- JSON object (if applicable)
    next_agent TEXT,
    priority TEXT,
    blocking_dependencies TEXT,       -- JSON array

    created_at TEXT NOT NULL,
    created_by TEXT
);

-- Indexes
CREATE INDEX idx_papers_source_type ON research_papers(source_type);
CREATE INDEX idx_papers_created_at ON research_papers(created_at);
CREATE INDEX idx_evaluations_overall_score ON evaluations(overall_score);
CREATE INDEX idx_recommendations_verdict ON recommendations(verdict);
```

### 4.2 Request/Response Contracts

```python
# ─────────────────────────────────────────────────────────────────────────────
# Ingest Phase
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class IngestPaperRequest:
    """Request to ingest a research paper."""
    source: str                       # URL, file path, or arxiv ID
    source_type: Optional[SourceType] = None  # Auto-detected if not provided
    title_override: Optional[str] = None
    metadata: Optional[dict] = None

@dataclass
class IngestPaperResponse:
    """Result of paper ingestion."""
    paper_id: str
    title: str
    source_type: SourceType
    word_count: int
    section_count: int
    extraction_confidence: float
    warnings: list[str]               # Any issues during extraction

# ─────────────────────────────────────────────────────────────────────────────
# Full Pipeline
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvaluatePaperRequest:
    """Request to run full evaluation pipeline."""
    source: str                       # URL, file path, or arxiv ID
    source_type: Optional[SourceType] = None
    context_documents: list[str] = field(default_factory=lambda: [
        "AGENTS.md", "PRD.md", "MCP_SERVER_DESIGN.md"
    ])
    llm_model: str = "claude-sonnet-4-20250514"
    save_to_db: bool = True

@dataclass
class EvaluatePaperResponse:
    """Complete evaluation result."""
    paper_id: str
    paper_title: str

    # Phase results
    comprehension: ComprehensionResult
    evaluation: EvaluationResult
    recommendation: Recommendation

    # Metadata
    total_tokens_used: int
    evaluation_duration_seconds: float

    # Formatted output
    markdown_report: str              # Full report in template format
```

---

## 5. CLI Commands

### Command Group: `amprealize research`

```bash
# Full pipeline (most common usage)
amprealize research evaluate --url https://arxiv.org/abs/2601.09259
amprealize research evaluate --file research/MAXS_paper.md
amprealize research evaluate --arxiv 2601.09259

# Individual phases (for debugging/testing)
amprealize research ingest --url https://example.com/paper.pdf --output paper.json
amprealize research comprehend --paper-id abc123
amprealize research score --paper-id abc123

# Management
amprealize research list [--verdict ADOPT] [--since 2025-01-01]
amprealize research get <paper-id> [--format json|markdown]
amprealize research compare <paper-id-1> <paper-id-2>
amprealize research export <paper-id> --output report.md

# Bulk operations
amprealize research batch-evaluate --input papers.txt --output results/
```

### CLI Options (Common)

| Option | Description | Default |
|--------|-------------|---------|
| `--output`, `-o` | Output file path | stdout |
| `--format`, `-f` | Output format (json, markdown, table) | markdown |
| `--model` | LLM model to use | claude-sonnet-4-20250514 |
| `--no-save` | Don't persist to database | False |
| `--verbose`, `-v` | Show progress and debug info | False |

---

## 6. MCP Tools

### Tool Catalog

| Tool | Description | Parameters |
|------|-------------|------------|
| `research.ingest` | Ingest paper from URL/file | `source`, `source_type?` |
| `research.evaluate` | Full evaluation pipeline | `source`, `source_type?`, `model?` |
| `research.comprehend` | Comprehension phase only | `paper_id` |
| `research.score` | Evaluation phase only | `paper_id` |
| `research.recommend` | Recommendation phase only | `paper_id` |
| `research.search` | Search evaluated papers | `query`, `verdict?`, `min_score?` |
| `research.get` | Get paper details | `paper_id`, `include_report?` |
| `research.compare` | Compare multiple papers | `paper_ids[]` |

### MCP Registration

```python
# In mcp_server.py MCPServiceRegistry

RESEARCH_TOOLS = [
    Tool(
        name="research.evaluate",
        description="Run full AI research evaluation pipeline on a paper",
        inputSchema={
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "URL, file path, or arxiv ID"
                },
                "source_type": {
                    "type": "string",
                    "enum": ["url", "arxiv", "markdown", "pdf"],
                    "description": "Source type (auto-detected if not provided)"
                },
                "model": {
                    "type": "string",
                    "description": "LLM model to use for evaluation"
                }
            },
            "required": ["source"]
        }
    ),
    # ... other tools
]
```

---

## 7. LLM Prompts

### 7.1 Comprehension Prompt

```markdown
You are an expert AI research analyst. Your task is to deeply comprehend the following research paper and extract structured information.

## Paper Content

{paper_text}

## Instructions

Analyze this paper thoroughly and provide a structured JSON response with the following fields:

1. **core_idea**: A 2-3 sentence summary of the paper's main contribution
2. **problem_addressed**: What problem does this research solve?
3. **proposed_solution**: How do the authors solve this problem?
4. **key_contributions**: List of 3-5 novel contributions (bullet points)
5. **technical_approach**: 1-2 paragraph explanation of how the approach works
6. **algorithms_methods**: Named algorithms, architectures, or methods introduced
7. **claimed_results**: Array of {metric, improvement, conditions} for each key result
8. **benchmarks_used**: Datasets and benchmarks used for evaluation
9. **limitations_acknowledged**: Self-reported limitations from the paper
10. **novelty_score**: 1-10 rating of how novel this work is (10 = groundbreaking)
11. **novelty_rationale**: Brief explanation of the novelty score
12. **related_work_summary**: How does this compare to prior art mentioned?
13. **comprehension_confidence**: 0-1 confidence in your understanding
14. **key_terms**: Important technical terms for indexing

## Response Format

Respond with valid JSON only, no additional text.
```

### 7.2 Evaluation Prompt

```markdown
You are an expert technical evaluator assessing whether AI research should be integrated into the Amprealize platform.

## Research Summary

{comprehension_result}

## Amprealize Context

### Current Architecture (from MCP_SERVER_DESIGN.md)
{mcp_server_context}

### Existing Behaviors (from AGENTS.md)
{agents_context}

### Product Requirements (from PRD.md)
{prd_context}

## Evaluation Criteria

Score each criterion from 1-10 and provide rationale:

1. **Relevance** (weight: 0.25): How applicable is this to Amprealize's mission of improving AI agent effectiveness?

2. **Feasibility** (weight: 0.25): Can we realistically implement this with our current team, stack, and timeline?

3. **Novelty** (weight: 0.20): Does this offer capabilities we don't already have? Avoid redundancy.

4. **ROI** (weight: 0.20): Is the expected benefit worth the implementation + ongoing maintenance cost?

5. **Safety** (weight: 0.10): Any alignment, security, reliability, or ethical concerns?

## Additional Analysis Required

- **Conflicts**: List any conflicts with existing behaviors or approaches in AGENTS.md
- **Implementation Complexity**: LOW, MEDIUM, HIGH, or VERY_HIGH
- **Maintenance Burden**: LOW, MEDIUM, HIGH, or VERY_HIGH
- **Expertise Gap**: Do we have the skills to implement this? LOW, MEDIUM, HIGH, VERY_HIGH
- **Concerns**: Be brutally honest about problems or risks
- **Benefits**: What would Amprealize gain from this?

## Response Format

Respond with valid JSON matching the EvaluationResult schema.
```

### 7.3 Recommendation Prompt

```markdown
Based on the evaluation below, provide a final recommendation.

## Evaluation Results

{evaluation_result}

## Verdict Options

- **ADOPT**: Overall score >= 7.5, implement as described
- **ADAPT**: Overall score 5.5-7.4, implement with modifications
- **DEFER**: Overall score 3.5-5.4, interesting but not now
- **REJECT**: Overall score < 3.5 OR safety score < 4.0

## If Recommending ADOPT or ADAPT

Provide an implementation roadmap including:

1. **Affected Components**: Which files/modules would change?
2. **Proposed Steps**: Ordered list of implementation steps
3. **Success Criteria**: How do we know it worked?
4. **Estimated Effort**: T-shirt size (S/M/L/XL) with justification
5. **Adaptations Needed** (if ADAPT): What modifications from original?

## Handoff Information

- **Next Agent**: Which agent should take this forward? (architect, engineering, product)
- **Priority**: P1 (urgent), P2 (important), P3 (normal), P4 (backlog)
- **Blocking Dependencies**: What must happen first?

## Response Format

Respond with valid JSON matching the Recommendation schema.
```

---

## 8. Output Template

All evaluations produce a standardized markdown report:

```markdown
# Research Evaluation Report

**Paper**: {title}
**Source**: {source_url}
**Evaluated**: {date}
**Agent**: AI Research Analyst
**Model**: {llm_model}

---

## 1. Comprehension Summary

### Core Idea
{core_idea}

### Problem Addressed
{problem_addressed}

### Proposed Solution
{proposed_solution}

### Key Contributions
{for contribution in key_contributions}
- {contribution}
{endfor}

### Technical Approach
{technical_approach}

### Claimed Results

| Metric | Improvement | Conditions |
|--------|-------------|------------|
{for result in claimed_results}
| {result.metric} | {result.improvement} | {result.conditions} |
{endfor}

### Novelty Assessment
**Score**: {novelty_score}/10
**Rationale**: {novelty_rationale}

---

## 2. Evaluation

### Scores

| Criterion | Score | Weight | Weighted |
|-----------|-------|--------|----------|
| Relevance | {relevance_score}/10 | 0.25 | {relevance_score * 0.25:.2f} |
| Feasibility | {feasibility_score}/10 | 0.25 | {feasibility_score * 0.25:.2f} |
| Novelty | {novelty_score}/10 | 0.20 | {novelty_score * 0.20:.2f} |
| ROI | {roi_score}/10 | 0.20 | {roi_score * 0.20:.2f} |
| Safety | {safety_score}/10 | 0.10 | {safety_score * 0.10:.2f} |
| **Overall** | | | **{overall_score:.2f}/10** |

### Relevance
{relevance_rationale}

### Feasibility
{feasibility_rationale}

### Novelty
{novelty_rationale}

### ROI
{roi_rationale}

### Safety
{safety_rationale}

### ⚠️ Conflicts with Existing Approach
{if conflicts}
{for conflict in conflicts}
- **{conflict.behavior_name}**: {conflict.description}
{endfor}
{else}
No conflicts detected.
{endif}

### Resource Assessment

| Factor | Rating | Notes |
|--------|--------|-------|
| Implementation Complexity | {implementation_complexity} | |
| Maintenance Burden | {maintenance_burden} | |
| Expertise Gap | {expertise_gap} | |
| **Estimated Effort** | {estimated_effort} | |

### ⚠️ Concerns
{for concern in concerns}
- {concern}
{endfor}

### ✅ Potential Benefits
{for benefit in potential_benefits}
- {benefit}
{endfor}

---

## 3. Recommendation

### Verdict: {verdict}

{verdict_rationale}

{if verdict in [ADOPT, ADAPT]}
### Implementation Roadmap

#### Affected Components
{for component in affected_components}
- `{component.path}`: {component.what_changes}
{endfor}

#### Proposed Steps
{for i, step in enumerate(proposed_steps, 1)}
{i}. {step}
{endfor}

#### Success Criteria
{for criterion in success_criteria}
- [ ] {criterion}
{endfor}

{if verdict == ADAPT}
#### Adaptations Needed
{for adaptation in adaptations_needed}
- {adaptation}
{endfor}
{endif}

### Handoff

| Field | Value |
|-------|-------|
| Next Agent | {next_agent} |
| Priority | {priority} |
| Blocking Dependencies | {blocking_dependencies or 'None'} |
{endif}

---

## 4. Metadata

| Field | Value |
|-------|-------|
| Paper ID | {paper_id} |
| Evaluation ID | {evaluation_id} |
| Tokens Used | {total_tokens_used} |
| Duration | {evaluation_duration_seconds:.1f}s |
| Comprehension Confidence | {comprehension_confidence:.0%} |
```

---

## 9. Implementation Phases

### Phase 1: MVP (Week 1-2)

**Goal**: Working CLI with full pipeline, SQLite storage

| Task | Priority | Effort |
|------|----------|--------|
| Create `research_contracts.py` with dataclasses | P1 | S |
| Implement `ingesters/` for URL + Markdown | P1 | M |
| Implement `research_service.py` core | P1 | L |
| Add SQLite storage layer | P1 | M |
| Create LLM prompts in `prompts/research_prompts.py` | P1 | M |
| Add `research` CLI commands | P1 | M |
| Create output template renderer | P1 | S |
| Test with MAXS paper | P1 | S |

**Deliverable**: `amprealize research evaluate --file paper.md` works end-to-end

### Phase 2: Enhanced Ingestion (Week 3)

**Goal**: PDF support, arxiv integration, URL improvements

| Task | Priority | Effort |
|------|----------|--------|
| Add `pymupdf` PDF ingester | P2 | M |
| Integrate arxiv API for metadata | P2 | M |
| Improve URL content extraction | P2 | M |
| Add ingestion quality scoring | P3 | S |

**Deliverable**: Can evaluate papers from arxiv URLs directly

### Phase 3: MCP Integration (Week 4)

**Goal**: Expose via MCP tools

| Task | Priority | Effort |
|------|----------|--------|
| Create `research_handlers.py` | P2 | M |
| Register tools in `mcp_server.py` | P2 | S |
| Add streaming progress updates | P3 | M |
| Test via VS Code extension | P2 | S |

**Deliverable**: `research.evaluate` MCP tool works from IDE

### Phase 4: PostgreSQL + API (Week 5+)

**Goal**: Production-ready storage and REST API

| Task | Priority | Effort |
|------|----------|--------|
| Create PostgreSQL schema migration | P3 | M |
| Implement `research_service_postgres.py` | P3 | L |
| Add REST API endpoints | P3 | M |
| Add comparison/search features | P4 | M |

---

## 10. Dependencies

### Python Packages

```toml
# pyproject.toml additions
[project.optional-dependencies]
research = [
    "httpx>=0.25.0",          # URL fetching
    "beautifulsoup4>=4.12.0", # HTML parsing
    "pymupdf>=1.23.0",        # PDF extraction
    "arxiv>=2.1.0",           # Arxiv API
    "tiktoken>=0.5.0",        # Token counting
]
```

### Existing Services

- `LLMClient` or equivalent for Claude API calls
- `RazeLogger` for structured logging
- Existing SQLite/PostgreSQL pool infrastructure

---

## 11. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Pipeline completion rate | >95% | Papers successfully evaluated / attempted |
| Evaluation consistency | >80% | Same paper → similar scores across runs |
| Time to evaluate | <60s | Average pipeline duration |
| Verdict accuracy | TBD | Human review of recommendations |
| Adoption rate | >30% | ADOPT/ADAPT verdicts that get implemented |

---

## 12. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| PDF extraction quality varies | High | Medium | Fallback to asking user for text; quality scoring |
| LLM scoring inconsistency | Medium | Medium | Use structured output; few-shot examples |
| Context documents too large | Medium | Low | Summarize/chunk context docs |
| Conflicts not detected | Low | High | Explicit conflict checking prompts |
| Over-optimistic recommendations | Medium | High | Calibration via human review feedback |

---

## 13. Open Questions

1. **Feedback loop**: How do we track whether ADOPT recommendations actually get implemented and succeed?

2. **Batch evaluation**: Should we support evaluating multiple papers and ranking them?

3. **Domain expertise**: Should different evaluators (prompts) exist for different research domains (NLP, RL, multi-agent, etc.)?

4. **Cost tracking**: Should we track LLM costs per evaluation for budgeting?

5. **Versioning**: If we re-evaluate a paper with updated context, how do we handle versions?

---

## Appendix A: File Locations

| Component | Path |
|-----------|------|
| Contracts | `amprealize/research_contracts.py` |
| Service | `amprealize/research_service.py` |
| Ingesters | `amprealize/research/ingesters/` |
| Prompts | `amprealize/research/prompts.py` |
| CLI | `amprealize/cli.py` (add research subparser) |
| MCP Handlers | `amprealize/mcp/handlers/research_handlers.py` |
| SQLite Schema | `schema/research_sqlite.sql` |
| PostgreSQL Migration | `schema/migrations/XXX_research_tables.sql` |
| Tests | `tests/test_research_service.py` |
| Output Template | `docs/templates/RESEARCH_EVALUATION_TEMPLATE.md` |

---

## Appendix B: Related Documents

- [AGENT_AI_RESEARCH.md](AGENT_AI_RESEARCH.md) - AI Research Agent playbook
- [AGENTS.md](AGENTS.md) - Behavior handbook for conflict detection
- [MCP_SERVER_DESIGN.md](docs/MCP_SERVER_DESIGN.md) - MCP tool patterns
- [BEHAVIOR_SERVICE_CONTRACT.md](BEHAVIOR_SERVICE_CONTRACT.md) - Service contract template

---

_Last Updated: 2025-01-20_
