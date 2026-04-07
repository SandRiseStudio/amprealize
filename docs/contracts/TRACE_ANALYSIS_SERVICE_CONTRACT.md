# TraceAnalysisService Contract

## Purpose
Provide automated behavior extraction from execution traces by detecting recurring patterns, scoring their reusability, and generating behavior candidates for the handbook. The service supports the Strategist → Teacher → Student workflow by mining production execution data to identify generalizable reasoning steps that can reduce token consumption and improve consistency. This contract implements **PRD Component B (Reflection Service)** and supports **PRD Goal 1: 70% behavior reuse** through continuous pattern discovery.

## Services & Endpoints
- **Service Module:** `amprealize.trace_analysis_service.TraceAnalysisService`
- **REST Base Path:** `/v1/trace-analysis` (planned)
- **CLI Commands:** `amprealize trace-analysis detect-patterns`, `amprealize trace-analysis score-pattern` (planned)
- **MCP Tools:** `traceAnalysis.detectPatterns`, `traceAnalysis.scoreReusability` (planned)

## Architecture Overview

### Data Flow
```
Execution Traces (RunService)
    ↓
TraceAnalysisService.segment() → List[TraceStep]
    ↓
TraceAnalysisService.detect_patterns() → Cross-trace pattern mining
    ↓
TraceAnalysisService.score_reusability() → Quality scoring (0-1 scale)
    ↓
PostgreSQL Storage (trace_patterns, pattern_occurrences, extraction_jobs)
    ↓
ReflectionService.reflect() → Behavior candidate generation
    ↓
BehaviorService.approve() → Handbook enrichment
```

### Integration Points
- **BCIService:** Trace segmentation via `segment_trace()` method
- **RunService:** Fetch execution traces via `get_run(run_id).trace_text` (TODO)
- **BehaviorService:** Submit approved patterns as behaviors
- **ReflectionService:** Generate behavior candidates from high-scoring patterns
- **MetricsService:** Track extraction rates, approval rates, duplicate reduction
- **PostgreSQL:** Persistence layer for patterns, occurrences, jobs, candidates

## Storage Backend

### PostgreSQL Schema
- **Database:** `behaviors` (shares amprealize-postgres-behavior container, port 5433)
- **Migration:** `schema/migrations/013_create_trace_analysis.sql` (370 lines)
- **Tables:** 4 (trace_patterns, pattern_occurrences, extraction_jobs, reflection_candidates)
- **Indexes:** 13 (frequency, score, time-based, GIN for JSONB)
- **Views:** 3 (high_value_patterns, extraction_jobs_summary, approval_funnel)
- **Triggers:** 2 (auto-update timestamps)
- **Functions:** 1 (calculate_pattern_similarity using Jaccard index)

## Data Contracts

### TracePattern
Represents a recurring sequence of reasoning steps discovered across multiple execution traces.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `pattern_id` | UUID | Yes | Stable identifier for the pattern. |
| `sequence` | List[str] | Yes | Ordered list of normalized step descriptions (1-5 steps). |
| `frequency` | int | Yes | Count of occurrences across all analyzed runs (≥ 1). |
| `first_seen` | ISO8601 | Yes | Timestamp of first occurrence discovery. |
| `last_seen` | ISO8601 | Yes | Timestamp of most recent occurrence. |
| `extracted_from_runs` | List[str] | Yes | Run IDs where pattern was observed (max 100 tracked). |
| `avg_tokens_per_step` | float | Yes | Estimated token count per step (~1.3 tokens/word). |
| `metadata` | Dict | No | Arbitrary JSON metadata (e.g., task types, domains). |

**Properties:**
- `sequence_length`: Computed as `len(sequence)`
- `total_token_count`: Computed as `avg_tokens_per_step * sequence_length`

**Example:**
```json
{
  "pattern_id": "550e8400-e29b-41d4-a716-446655440000",
  "sequence": [
    "identify target variable",
    "list known values",
    "apply formula",
    "verify units match"
  ],
  "frequency": 12,
  "first_seen": "2025-10-25T14:32:00Z",
  "last_seen": "2025-10-29T09:15:00Z",
  "extracted_from_runs": ["run-abc", "run-def", "run-ghi"],
  "avg_tokens_per_step": 8.5,
  "metadata": {"domain": "physics", "task_type": "calculation"}
}
```

### PatternOccurrence
Represents a single instance of a pattern appearing within an execution trace.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `occurrence_id` | UUID | Yes | Unique identifier for this occurrence. |
| `pattern_id` | UUID | Yes | Foreign key to parent TracePattern. |
| `run_id` | str | Yes | Execution run where pattern occurred. |
| `occurrence_time` | ISO8601 | Yes | Timestamp when pattern was detected. |
| `start_step_index` | int | Yes | Zero-based index of first step in trace (≥ 0). |
| `end_step_index` | int | Yes | Zero-based index of last step in trace (≥ start_step_index). |
| `context_before` | List[str] | No | Up to 3 steps preceding the pattern. |
| `context_after` | List[str] | No | Up to 3 steps following the pattern. |
| `token_count` | int | No | Estimated tokens for this occurrence. |

**Properties:**
- `step_span`: Computed as `end_step_index - start_step_index + 1`

**Example:**
```json
{
  "occurrence_id": "660e8400-e29b-41d4-a716-446655440001",
  "pattern_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "run-abc-123",
  "occurrence_time": "2025-10-29T09:15:00Z",
  "start_step_index": 5,
  "end_step_index": 8,
  "context_before": ["read problem statement", "identify givens"],
  "context_after": ["calculate result", "format answer"],
  "token_count": 34
}
```

### ReusabilityScore
Quality metrics for a pattern indicating its value for inclusion in the behavior handbook.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `pattern_id` | UUID | Yes | Pattern being scored. |
| `frequency_score` | float | Yes | Normalized frequency (0-1): `pattern.frequency / total_runs`. |
| `token_savings_score` | float | Yes | Potential token reduction (0-1): based on `avg_tokens_per_step` and reuse potential. |
| `applicability_score` | float | Yes | Cross-domain applicability (0-1): `unique_task_types / total_task_types`. |
| `overall_score` | float | Yes | Weighted average: `0.4*frequency + 0.3*token_savings + 0.3*applicability`. |
| `calculated_at` | ISO8601 | Yes | Timestamp of score calculation. |
| `metadata` | Dict | No | Scoring context (e.g., corpus size, thresholds). |

**Properties:**
- `meets_approval_threshold`: Boolean computed as `overall_score > 0.7`

**Scoring Formula (from PRD):**
```
overall_score = 0.4 × frequency_score
              + 0.3 × token_savings_score
              + 0.3 × applicability_score

where:
  frequency_score = pattern.frequency / total_runs_in_corpus
  token_savings_score = min(1.0, (pattern.total_token_count / avg_trace_tokens) * 10)
  applicability_score = unique_task_types_for_pattern / total_task_types_in_corpus
```

**Approval Threshold:** Patterns with `overall_score > 0.7` are automatically submitted to ReflectionService for candidate generation (PRD target: 80% approval rate).

**Example:**
```json
{
  "pattern_id": "550e8400-e29b-41d4-a716-446655440000",
  "frequency_score": 0.6,
  "token_savings_score": 0.75,
  "applicability_score": 0.85,
  "overall_score": 0.715,
  "calculated_at": "2025-10-29T10:00:00Z",
  "metadata": {
    "total_runs": 20,
    "avg_trace_tokens": 150,
    "unique_task_types": 5,
    "total_task_types": 6
  }
}
```

### ExtractionJob
Represents a batch pattern extraction job analyzing multiple execution runs.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `job_id` | UUID | Yes | Unique job identifier. |
| `status` | enum | Yes | `PENDING \| RUNNING \| COMPLETE \| FAILED`. |
| `start_time` | ISO8601 | No | Job start timestamp (null if PENDING). |
| `end_time` | ISO8601 | No | Job completion timestamp (null if not finished). |
| `runs_analyzed` | int | Yes | Count of execution runs processed (≥ 0). |
| `patterns_found` | int | Yes | Count of unique patterns discovered (≥ 0). |
| `candidates_generated` | int | Yes | Count of behavior candidates created (≥ 0). |
| `error_message` | str | No | Error description if status=FAILED. |
| `metadata` | Dict | No | Job configuration (e.g., min_frequency, min_similarity). |

**Properties:**
- `duration_seconds`: Computed as `(end_time - start_time).total_seconds()` if both timestamps present
- `extraction_rate`: Computed as `candidates_generated / runs_analyzed` (PRD target: ≥ 0.05)

**Example:**
```json
{
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "COMPLETE",
  "start_time": "2025-10-29T02:00:00Z",
  "end_time": "2025-10-29T02:15:30Z",
  "runs_analyzed": 50,
  "patterns_found": 8,
  "candidates_generated": 3,
  "error_message": null,
  "metadata": {
    "min_frequency": 3,
    "min_similarity": 0.7,
    "date_range": "2025-10-28"
  }
}
```

## Service Methods

### segment(trace_text: str, trace_format: str = "MARKDOWN") → List[TraceStep]
**Purpose:** Parse execution trace into structured steps for pattern analysis.

**Parameters:**
- `trace_text` (str): Raw trace content from RunService
- `trace_format` (str): Format hint ("MARKDOWN" | "JSON" | "PLAIN_TEXT")

**Returns:** List of TraceStep objects (from `bci_contracts.py`)

**Algorithm:**
1. Delegate to BCIService.segment_trace()
2. Parse trace into steps with step_type, description, metadata
3. Return List[TraceStep] for downstream processing

**Example:**
```python
service = TraceAnalysisService(bci_service=bci)
steps = service.segment(trace_text="## Step 1\nIdentify variables...", trace_format="MARKDOWN")
# Returns: [TraceStep(step_type="reasoning", description="Identify variables", ...)]
```

### iter_snippets(steps: List[TraceStep], window_sizes: List[int] = [3, 4, 5]) → Iterator[_Snippet]
**Purpose:** Generate sliding window snippets from trace steps for ReflectionService analysis.

**Parameters:**
- `steps` (List[TraceStep]): Parsed trace steps
- `window_sizes` (List[int]): Snippet lengths to generate

**Returns:** Iterator yielding `_Snippet(text: str, steps: List[TraceStep])` objects

**Filtering:** Skips snippets with < 4 words (noise reduction)

**Example:**
```python
steps = [TraceStep(...), TraceStep(...), TraceStep(...), TraceStep(...)]
for snippet in service.iter_snippets(steps, window_sizes=[3, 4]):
    print(snippet.text)  # 3-step or 4-step window text
```

### detect_patterns(request: DetectPatternsRequest) → DetectPatternsResponse
**Purpose:** Cross-trace pattern mining to identify recurring reasoning sequences.

**Request Schema:**
```python
@dataclass
class DetectPatternsRequest(SerializableDataclass):
    run_ids: List[str]              # Execution runs to analyze
    min_frequency: int = 3          # Minimum occurrences to qualify as pattern
    min_similarity: float = 0.7     # SequenceMatcher threshold (0-1)
    max_patterns: int = 100         # Limit returned patterns
    include_context: bool = True    # Include context_before/after in occurrences
```

**Response Schema:**
```python
@dataclass
class DetectPatternsResponse(SerializableDataclass):
    patterns: List[TracePattern]    # Discovered patterns sorted by frequency DESC
    runs_analyzed: int              # Count of runs successfully processed
    total_occurrences: int          # Sum of all pattern occurrences
    execution_time_seconds: float   # Processing duration
    metadata: Dict                  # Algorithm config, warnings
```

**Algorithm (10 steps):**
1. **Fetch traces:** Retrieve trace_text for each run_id via RunService (TODO: implement)
2. **Segment traces:** Call `segment()` for each trace → List[List[TraceStep]]
3. **Extract sequences:** Sliding windows (1-5 steps) from each trace
4. **Normalize steps:** Remove punctuation, lowercase, strip whitespace
5. **Group similar sequences:** Use `_calculate_sequence_similarity()` with SequenceMatcher.ratio() averaged across steps, min_similarity threshold
6. **Count frequency:** Track occurrences per pattern across runs
7. **Filter by frequency:** Keep patterns with occurrence count ≥ min_frequency
8. **Sort by frequency:** Order patterns DESC by occurrence count
9. **Limit results:** Return top max_patterns
10. **Store to PostgreSQL:** Save patterns and occurrences if storage backend configured

**Complexity:** O(R × S² × W) where R=runs, S=steps per trace, W=window sizes

**Example:**
```python
request = DetectPatternsRequest(
    run_ids=["run-001", "run-002", "run-003"],
    min_frequency=2,
    min_similarity=0.7,
    max_patterns=50
)
response = service.detect_patterns(request)
print(f"Found {len(response.patterns)} patterns in {response.execution_time_seconds:.2f}s")
```

### score_reusability(request: ScoreReusabilityRequest) → ScoreReusabilityResponse
**Purpose:** Calculate quality metrics for a pattern to determine handbook inclusion eligibility.

**Request Schema:**
```python
@dataclass
class ScoreReusabilityRequest(SerializableDataclass):
    pattern_id: str                 # Pattern to score
    total_runs: int                 # Corpus size for frequency_score
    avg_trace_tokens: float         # Corpus average for token_savings_score
    unique_task_types: int          # Pattern task diversity
    total_task_types: int           # Corpus task diversity for applicability_score
```

**Response Schema:**
```python
@dataclass
class ScoreReusabilityResponse(SerializableDataclass):
    score: ReusabilityScore         # Calculated scores
    pattern: TracePattern           # Pattern being scored
    meets_threshold: bool           # overall_score > 0.7
```

**Algorithm:**
1. Fetch pattern from storage (or use provided pattern for testing)
2. Call `ReusabilityScore.calculate()` static method with corpus metrics
3. Calculate frequency_score = pattern.frequency / total_runs
4. Calculate token_savings_score = min(1.0, (pattern.total_token_count / avg_trace_tokens) * 10)
5. Calculate applicability_score = unique_task_types / total_task_types
6. Calculate overall_score = 0.4*frequency + 0.3*token_savings + 0.3*applicability
7. Store scores to PostgreSQL via storage.update_pattern_scores()
8. Return ScoreReusabilityResponse with score, pattern, meets_threshold

**Example:**
```python
request = ScoreReusabilityRequest(
    pattern_id="550e8400-e29b-41d4-a716-446655440000",
    total_runs=100,
    avg_trace_tokens=200,
    unique_task_types=5,
    total_task_types=10
)
response = service.score_reusability(request)
if response.meets_threshold:
    print(f"Pattern eligible for handbook (score: {response.score.overall_score:.3f})")
```

## PostgreSQL Storage Layer (TODO: Todo 5)

### PostgresTraceAnalysisService
**Status:** Not yet implemented (estimated 300-400 lines, 4-6 hours)

**Methods (planned):**
- `store_pattern(pattern: TracePattern) → str`: INSERT into trace_patterns, return pattern_id
- `get_pattern(pattern_id: str) → TracePattern`: SELECT from trace_patterns with JSONB deserialization
- `update_pattern_scores(pattern_id, frequency_score, token_savings_score, applicability_score, overall_score) → None`: UPDATE trace_patterns scores columns
- `store_occurrence(occurrence: PatternOccurrence) → str`: INSERT into pattern_occurrences with composite PK
- `get_occurrences_by_pattern(pattern_id: str, limit: int = 100) → List[PatternOccurrence]`: SELECT with occurrence_time DESC
- `get_occurrences_by_run(run_id: str, limit: int = 100) → List[PatternOccurrence]`: SELECT with JOIN
- `store_extraction_job(job: ExtractionJob) → str`: INSERT into extraction_jobs, return job_id
- `get_extraction_job(job_id: str) → ExtractionJob`: SELECT from extraction_jobs
- `update_extraction_job_status(job_id, status, end_time, error_message) → None`: UPDATE extraction_jobs status

**Caching Strategy (Redis):**
- Pattern cache: 600s TTL, cache-first for get_pattern()
- Occurrence cache: 300s TTL for get_occurrences_by_pattern()
- Job cache: No caching (status updates require fresh data)

**Configuration:**
- Environment variable: `AMPREALIZE_TRACE_ANALYSIS_PG_DSN` (defaults to POSTGRES_CONNECTION_STRING_BEHAVIOR if unset)
- Connection pool: Use `PostgresPool` from `amprealize/storage/postgres_pool.py`
- Service name: "trace_analysis" for metrics/telemetry

## Batch Processing (TODO: Todo 6)

### scripts/nightly_reflection.py
**Status:** Not yet implemented (estimated 200 lines, 3-4 hours)

**Workflow:**
1. Fetch yesterday's completed runs via RunService.list_runs(start_date, end_date, status='COMPLETE')
2. Create ExtractionJob with status=PENDING
3. Call TraceAnalysisService.detect_patterns(run_ids) with default thresholds
4. For each pattern discovered, call score_reusability()
5. Filter patterns with overall_score > 0.7
6. Generate ReflectionCandidate for each high-scoring pattern
7. Submit candidates to ReflectionService.reflect() for approval workflow
8. Update ExtractionJob status=COMPLETE with metrics (runs_analyzed, patterns_found, candidates_generated)
9. Emit telemetry event: trace_analysis.extraction_job_complete

**Scheduling:**
- Cron: `0 2 * * * /usr/bin/python3 /path/to/scripts/nightly_reflection.py` (2 AM daily)
- Systemd timer alternative for Linux environments

**Error Handling:**
- Catch exceptions, set ExtractionJob status=FAILED
- Store error_message and stack trace in extraction_jobs.error_message
- Emit telemetry event: trace_analysis.extraction_job_failed

## Quality Rubric

### Pattern Detection Quality
- **Precision:** % of detected patterns that are meaningful (not noise)
  - Target: ≥ 85% patterns manually reviewable
  - Measurement: Sample 20 patterns, manual review for coherence
- **Recall:** % of actual recurring patterns discovered
  - Target: ≥ 70% coverage of ground truth patterns
  - Measurement: Annotated test corpus with known patterns
- **False Positive Rate:** % of patterns that are spurious
  - Target: ≤ 15% spurious patterns
  - Measurement: Duplicate detection, trivial sequence filtering

### Scoring Accuracy
- **Score Stability:** Overall_score variance across repeated runs
  - Target: < 5% variance for same pattern
  - Measurement: Run scoring 10 times, calculate std dev
- **Threshold Calibration:** % of auto-approved patterns (score > 0.7) that receive human approval
  - Target: ≥ 80% approval rate (PRD target)
  - Measurement: Track approval_status in reflection_candidates table

### Extraction Rate
- **Candidates per Run:** Average number of behavior candidates generated per analyzed run
  - Target: ≥ 0.05 (PRD target, 1 candidate per 20 runs)
  - Measurement: extraction_rate property on ExtractionJob
- **Duplicate Reduction:** % of candidates rejected as duplicates
  - Target: ≥ 50% duplicate detection (PRD target)
  - Measurement: approval_funnel view duplicate_reduction_pct column

## Telemetry Events (TODO: Todo 10)

### trace_analysis.pattern_detected
**When:** After detect_patterns() identifies a new pattern
**Payload:**
```json
{
  "pattern_id": "550e8400-e29b-41d4-a716-446655440000",
  "sequence_length": 4,
  "frequency": 5,
  "runs_analyzed": 10,
  "min_frequency_threshold": 3,
  "min_similarity_threshold": 0.7,
  "execution_time_ms": 1250
}
```

### trace_analysis.extraction_job_complete
**When:** After nightly_reflection.py completes successfully
**Payload:**
```json
{
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "COMPLETE",
  "runs_analyzed": 50,
  "patterns_found": 8,
  "candidates_generated": 3,
  "extraction_rate": 0.06,
  "duration_seconds": 930
}
```

### trace_analysis.candidate_generated
**When:** After high-scoring pattern generates ReflectionCandidate
**Payload:**
```json
{
  "candidate_id": "880e8400-e29b-41d4-a716-446655440003",
  "pattern_id": "550e8400-e29b-41d4-a716-446655440000",
  "overall_score": 0.715,
  "slug": "behavior_physics_calculation_workflow",
  "approval_status": "PENDING"
}
```

## Testing Strategy (TODO: Todo 8)

### Test Coverage Target
- **Unit Tests:** ≥ 80% line coverage
- **Integration Tests:** ≥ 70% critical path coverage
- **Parity Tests:** 100% CLI/API/MCP surface consistency

### Test Classes (test_trace_analysis.py, 20+ tests)
1. **TestPatternDetection (5-7 tests):**
   - test_simple_sequence: Single-step pattern detection
   - test_recurring_pattern: Multi-run frequency counting
   - test_similarity_threshold: Min_similarity filtering
   - test_frequency_threshold: Min_frequency filtering
   - test_cross_run_detection: Pattern spans multiple runs
   - test_sliding_window: 1-5 step sequence extraction
   - test_edge_cases: Empty runs, single run, no patterns

2. **TestReusabilityScoring (4-5 tests):**
   - test_frequency_score: pattern.frequency / total_runs calculation
   - test_token_savings_score: Token savings estimation accuracy
   - test_applicability_score: Cross-task type applicability
   - test_overall_score: Weighted average formula
   - test_approval_threshold: meets_approval_threshold property

3. **TestBatchProcessing (3-4 tests):**
   - test_extraction_job_lifecycle: PENDING → RUNNING → COMPLETE
   - test_error_handling: FAILED status with error_message
   - test_extraction_rate_calculation: candidates_generated / runs_analyzed
   - test_metric_tracking: runs_analyzed, patterns_found, candidates_generated

4. **TestPostgreSQLStorage (5-7 tests):**
   - test_store_pattern: INSERT with JSONB
   - test_get_pattern: SELECT with deserialization
   - test_update_pattern_scores: UPDATE scores columns
   - test_store_occurrence: INSERT with composite PK
   - test_get_occurrences_by_pattern: SELECT with filtering
   - test_store_extraction_job: INSERT extraction_jobs
   - test_job_status_updates: UPDATE status flow

5. **TestCacheInvalidation (2-3 tests):**
   - test_pattern_cache_hit: Redis caching effectiveness
   - test_cache_invalidation_on_update: Scores update clears cache
   - test_cache_ttl: 600s expiration

6. **TestMultiTenantIsolation (1 test):**
   - test_pattern_isolation: Patterns scoped to run_ids

## Performance Targets

### Latency
- **detect_patterns():** < 5 seconds for 100 runs (avg 2,000 tokens/run)
- **score_reusability():** < 100ms per pattern
- **nightly_reflection.py:** < 15 minutes for 1,000 runs

### Throughput
- **Pattern detection:** ≥ 20 runs/second
- **Score calculation:** ≥ 100 patterns/second
- **Batch job:** ≥ 1,000 runs/night

### Resource Constraints
- **Memory:** < 2GB per nightly_reflection.py process
- **Database:** < 10GB storage for 100K patterns
- **Cache:** < 500MB Redis memory for pattern cache

## Success Metrics (from PRD)

### Primary Metrics
- **Behavior Reuse Rate:** 70% of runs cite ≥1 behavior (enabled by pattern mining)
- **Token Savings:** 30% reduction vs baseline (behaviors compress reasoning)
- **Extraction Rate:** ≥ 0.05 candidates per run (1 per 20 runs)
- **Approval Rate:** ≥ 80% of auto-generated candidates approved by reviewers

### Secondary Metrics
- **Duplicate Reduction:** ≥ 50% of candidates flagged as duplicates before submission
- **Handbook Growth Rate:** +10 approved behaviors per week via automated extraction
- **Pattern Recall:** ≥ 70% of ground-truth patterns discovered
- **False Positive Rate:** ≤ 15% spurious patterns

## Migration Path (Phase 4 Item 4)

### Current Status (50% Complete, 2025-10-29)
- ✅ Contracts designed (trace_analysis_contracts.py, 290 lines)
- ✅ PostgreSQL schema deployed (013_create_trace_analysis.sql, 370 lines)
- ✅ Core service implemented (trace_analysis_service.py, 450 lines)
- ✅ Refactored from reflection_service.py (backward compatibility maintained)
- ⏳ PostgreSQL storage layer (Todo 5, 4-6 hours)
- ⏳ Batch processing infrastructure (Todo 6, 3-4 hours)
- ⏳ Comprehensive test suite (Todo 8, 2-3 days)
- ⏳ CLI/API/MCP integration (Todo 9, 1 day)
- ⏳ Telemetry tracking (Todo 10, 4-6 hours)

### Completion Roadmap (1-1.5 weeks to 100%)
1. **Week 1, Days 1-2:** Implement PostgresTraceAnalysisService (Todo 5) + unit tests
2. **Week 1, Days 3-5:** Build comprehensive test suite (Todo 8, 20+ tests)
3. **Week 2, Day 1:** Implement nightly_reflection.py batch job (Todo 6)
4. **Week 2, Day 2:** Wire CLI/API/MCP surfaces (Todo 9) + parity tests
5. **Week 2, Day 3:** Add telemetry tracking (Todo 10) + validation

### Rollout Plan
- **Phase 1:** PostgreSQL storage + unit tests → Validate CRUD operations
- **Phase 2:** Batch processing → Run nightly job on test corpus (100 runs)
- **Phase 3:** Manual review → Sample 20 candidates for quality validation
- **Phase 4:** CLI/API integration → Enable on-demand pattern detection
- **Phase 5:** Production deployment → Enable nightly reflection on full corpus (1,000+ runs/day)

## Dependencies

### Service Dependencies
- **BCIService:** Trace segmentation (segment_trace method)
- **RunService:** Fetch execution traces (get_run method, TODO)
- **BehaviorService:** Submit approved patterns as behaviors
- **ReflectionService:** Generate behavior candidates from patterns
- **MetricsService:** Track extraction metrics

### Infrastructure Dependencies
- **PostgreSQL 16.10:** Database backend (postgres-behavior container, port 5433)
- **Redis:** Caching layer (pattern cache 600s TTL)
- **Podman/Docker:** Container orchestration
- **Cron/Systemd:** Batch job scheduling

### Python Dependencies
- `psycopg2`: PostgreSQL driver
- `difflib.SequenceMatcher`: Sequence similarity calculation
- `uuid`: Pattern/occurrence ID generation
- `datetime`: Timestamp handling
- `json`: JSONB serialization

## Compliance & Security

### Data Privacy
- **PII Handling:** Trace text may contain user inputs; anonymize before storage
- **Retention Policy:** Patterns stored indefinitely; occurrences pruned after 1 year
- **Access Control:** Read-only access for analytics; write access restricted to service accounts

### Audit Trail
- **Pattern Creation:** Log pattern_id, extracted_from_runs, created_at in trace_patterns table
- **Approval Workflow:** Link reflection_candidates to behavior_service approvals via created_behavior_id
- **Extraction Jobs:** Store job_id, status, runs_analyzed, duration in extraction_jobs table for reproducibility

### Rate Limiting
- **detect_patterns():** Max 1,000 run_ids per request
- **Batch job:** Max 10,000 runs per nightly job
- **PostgreSQL:** Connection pool limits (max 20 connections per service)

## Example Workflows

### On-Demand Pattern Detection (CLI)
```bash
# Analyze specific runs
amprealize trace-analysis detect-patterns \
  --run-ids run-001,run-002,run-003 \
  --min-frequency 2 \
  --min-similarity 0.7 \
  --max-patterns 50 \
  --output patterns.json

# Score a pattern
amprealize trace-analysis score-pattern \
  --pattern-id 550e8400-e29b-41d4-a716-446655440000 \
  --total-runs 100 \
  --avg-trace-tokens 200
```

### Automated Nightly Extraction (Cron)
```bash
# Install cron job
(crontab -l 2>/dev/null; echo "0 2 * * * cd /path/to/amprealize && python scripts/nightly_reflection.py >> /var/log/amprealize/reflection.log 2>&1") | crontab -

# Run manually for testing
python scripts/nightly_reflection.py --date 2025-10-28 --dry-run
```

### Programmatic Integration (Python)
```python
from amprealize.trace_analysis_service import TraceAnalysisService
from amprealize.trace_analysis_contracts import DetectPatternsRequest
from amprealize.bci_service import BCIService

# Initialize service
bci = BCIService()
service = TraceAnalysisService(bci_service=bci)

# Detect patterns
request = DetectPatternsRequest(
    run_ids=["run-001", "run-002"],
    min_frequency=2
)
response = service.detect_patterns(request)

print(f"Found {len(response.patterns)} patterns:")
for pattern in response.patterns:
    print(f"  - {pattern.pattern_id}: {pattern.sequence} (freq: {pattern.frequency})")
```

## References
- **PRD:** `PRD.md` Component B (Reflection Service), Goal 1 (70% behavior reuse)
- **MCP Server Design:** `MCP_SERVER_DESIGN.md` BehaviorService integration
- **Telemetry Schema:** `TELEMETRY_SCHEMA.md` event definitions
- **Action Registry:** `ACTION_REGISTRY_SPEC.md` reproducibility requirements
- **Build Timeline:** `BUILD_TIMELINE.md` entry #109 (TraceAnalysisService 50% complete)
- **Progress Tracker:** `PROGRESS_TRACKER.md` Phase 4 Item 4 status

---

_Last Updated: 2025-10-29_
_Status: 50% Complete (Contracts + Schema + Core Service)_
_Next Milestone: PostgreSQL Storage Layer (Todo 5, 4-6 hours)_
