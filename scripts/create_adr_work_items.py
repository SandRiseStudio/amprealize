#!/usr/bin/env python3
"""Create work items from ADR-0002 directly into a project board."""

import sys
sys.path.insert(0, '.')

from amprealize.services.board_service import BoardService, Actor
from amprealize.multi_tenant.board_contracts import (
    CreateWorkItemRequest, WorkItemType, WorkItemPriority
)

def main():
    # Initialize
    board_service = BoardService()
    project_id = "proj-3df1929a629b"
    actor = Actor(id="architect-agent", role="TEACHER", surface="cli")

    # Get board and first column
    boards = board_service.list_boards(project_id=project_id)
    if not boards:
        print(f"❌ No boards found for project {project_id}")
        sys.exit(1)

    board = boards[0]
    print(f"✅ Found board: {board.board_id}")

    columns = board_service.list_columns(board.board_id)
    first_column = columns[0] if columns else None
    if not first_column:
        print("❌ No columns found")
        sys.exit(1)

    print(f"✅ Using column: {first_column.name}")

    # Create implementation story
    story_request = CreateWorkItemRequest(
        board_id=board.board_id,
        column_id=first_column.column_id,
        title="[Implementation] Paradigm-Aware Behavior Adaptation Framework",
        description="""## Implementation Story

Based on ADR: `ADR-0002-adaptation-of-agentic-ai.md`

### Objective
Implement the Paradigm-Aware Behavior Adaptation Framework that categorizes behaviors into four adaptation paradigms (A1, A2, T1, T2) based on the research taxonomy.

### Key Features
- Internal-only paradigm tracking (not exposed to users)
- Automatic paradigm detection from execution traces
- Efficiency metrics tracking (tokens, duration, success rate)
- Paradigm-aware behavior selection with efficiency boosts

### Acceptance Criteria
- [ ] Paradigm enum and metadata added to behavior model
- [ ] Heuristic paradigm detection implemented
- [ ] Efficiency metrics tracking in place
- [ ] Paradigm-aware behavior router working
- [ ] Internal API endpoints for metrics
- [ ] Migration script for existing behaviors

### References
- ADR: docs/adr/ADR-0002-adaptation-of-agentic-ai.md
""",
        item_type=WorkItemType.STORY,
        priority=WorkItemPriority.HIGH,
        labels=["engineering", "implementation", "adopt"],
        metadata={
            "adr": "ADR-0002-adaptation-of-agentic-ai.md",
            "source": "architect-agent",
        },
    )

    story = board_service.create_work_item(story_request, actor)
    print(f"✅ Created story: {story.item_id}")

    # Tasks from ADR Phase 1-3
    tasks = [
        {
            "title": "Add paradigm enum and metadata to behavior model",
            "description": """## Task: Data Models

Add the following to `amprealize/models/behavior.py`:
- `AdaptationParadigm` enum (A1, A2, T1, T2, UNKNOWN)
- `ParadigmMetrics` dataclass for efficiency tracking
- Extend `BehaviorMetadata` with paradigm fields (internal only)

### Files to Modify
- `amprealize/models/behavior.py`

### Done When
- [ ] AdaptationParadigm enum defined
- [ ] ParadigmMetrics dataclass with token/duration/success tracking
- [ ] BehaviorMetadata extended with _paradigm fields
- [ ] Tests added
""",
            "effort": "S",
            "files": ["amprealize/models/behavior.py"],
        },
        {
            "title": "Implement heuristic paradigm detection",
            "description": """## Task: Trace Analysis

Implement paradigm detection in `TraceAnalysisService`:
- Analyze tool call patterns to detect T1 (general tools)
- Detect T2 pattern (agent feedback -> tool modification)
- Identify A1 (prompt iteration with tool feedback)
- Flag A2 for escalation (requires model adaptation)

### Files to Modify
- `amprealize/services/trace_analysis_service.py`

### Done When
- [ ] `detect_paradigm(trace)` method returns (paradigm, confidence)
- [ ] Helper methods for each pattern type
- [ ] 85% accuracy on test cases
- [ ] Unit tests covering all paradigm types
""",
            "effort": "M",
            "files": ["amprealize/services/trace_analysis_service.py"],
        },
        {
            "title": "Create efficiency metrics tracking",
            "description": """## Task: Metrics Infrastructure

Create database migration and service for paradigm metrics:
- Add paradigm columns to behavior_metadata table
- Create paradigm_metrics table
- Implement metrics aggregation in ParadigmService

### Files to Modify
- `migrations/20260121_add_paradigm_tracking.sql`
- `amprealize/services/paradigm_service.py`
- `amprealize/services/behavior_service.py`

### Done When
- [ ] Migration script runs successfully
- [ ] Metrics updated after each behavior execution
- [ ] Aggregation by paradigm working
- [ ] Integration tests passing
""",
            "effort": "M",
            "files": ["migrations/", "amprealize/services/paradigm_service.py"],
        },
        {
            "title": "Build paradigm-aware behavior router",
            "description": """## Task: Smart Routing

Enhance AgentOrchestratorService with paradigm-aware selection:
- Boost T1/T2 behaviors (more efficient)
- Slight penalty for A2 behaviors
- Consider success rate in routing decisions

### Files to Modify
- `amprealize/services/agent_orchestrator_service.py`

### Done When
- [ ] `_select_behavior_with_paradigm_awareness()` implemented
- [ ] Efficiency boost factors configurable
- [ ] A/B test framework for measuring improvement
- [ ] Parity tests across CLI/API/MCP
""",
            "effort": "M",
            "files": ["amprealize/services/agent_orchestrator_service.py"],
        },
        {
            "title": "Add paradigm optimization to behavior extraction",
            "description": """## Task: Extraction Enhancement

Update behavior extraction pipeline to classify paradigm at creation:
- Call paradigm detection after trace analysis
- Store paradigm metadata on new behaviors
- Log paradigm classification events via Raze

### Files to Modify
- `amprealize/services/behavior_service.py`
- `amprealize/research/codebase_analyzer.py`

### Done When
- [ ] New behaviors get paradigm classification
- [ ] Classification logged with Raze
- [ ] Confidence threshold configurable
- [ ] Unit tests for extraction + classification
""",
            "effort": "S",
            "files": ["amprealize/services/behavior_service.py"],
        },
        {
            "title": "Implement paradigm efficiency dashboard",
            "description": """## Task: Internal Dashboard

Create internal API endpoints and dashboard for paradigm metrics:
- `/internal/paradigm/metrics` - metrics by paradigm
- `/internal/paradigm/efficiency-report` - comparative analysis
- `/internal/paradigm/reclassify` - trigger reclassification

### Files to Modify
- `amprealize/api/internal/paradigm.py`
- `amprealize/api/internal/__init__.py`

### Done When
- [ ] All 3 endpoints implemented
- [ ] Internal auth required
- [ ] Efficiency report shows relative performance
- [ ] API tests passing
""",
            "effort": "M",
            "files": ["amprealize/api/internal/paradigm.py"],
        },
    ]

    for task_data in tasks:
        task_request = CreateWorkItemRequest(
            board_id=board.board_id,
            column_id=first_column.column_id,
            title=task_data['title'],
            description=task_data['description'],
            item_type=WorkItemType.TASK,
            priority=WorkItemPriority.MEDIUM,
            labels=["engineering", "implementation"],
            parent_id=story.item_id,
            metadata={
                "effort": task_data['effort'],
                "files": task_data['files'],
                "source": "architect-agent",
                "adr": "ADR-0002",
            },
        )

        task = board_service.create_work_item(task_request, actor)
        print(f"   ✓ Created task: {task.item_id} - {task_data['title'][:50]}")

    print(f"\n✅ Created 1 story + {len(tasks)} tasks in project {project_id}")


if __name__ == "__main__":
    main()
