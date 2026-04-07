"""Integration tests for WorkflowService and CLI commands.

Validates:
- Template CRUD operations
- Workflow execution with behavior-conditioned inference
- Token accounting and behavior reuse metrics
- CLI/API parity
- Role-specific execution paths
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from amprealize.action_contracts import Actor
from amprealize.workflow_service import (
    TemplateStep,
    WorkflowRole,
    WorkflowService,
    WorkflowStatus,
)
from amprealize.behavior_service import BehaviorService
from amprealize.adapters import CLIWorkflowServiceAdapter


@pytest.fixture
def mock_behavior_service():
    """Mock BehaviorService that returns sample behaviors."""
    service = MagicMock(spec=BehaviorService)
    service.get_behavior.return_value = {
        "behavior_id": "bhv-test001",
        "name": "behavior_test_pattern",
        "description": "A test behavior for validation",
        "instruction": "Follow this test pattern",
        "status": "APPROVED",
    }
    return service


@pytest.fixture(autouse=True)
def clean_workflow_db(postgres_dsn_workflow):
    """Clean workflow tables between tests to prevent state bleed."""
    from conftest import safe_truncate
    from amprealize.storage.redis_cache import get_cache

    safe_truncate(postgres_dsn_workflow, ["workflow_runs", "workflow_template_versions", "workflow_templates"])

    cache = get_cache()
    cache.invalidate_service("workflow")
    yield
    cache.invalidate_service("workflow")


@pytest.fixture
def workflow_service(postgres_dsn_workflow, mock_behavior_service, clean_workflow_db):
    """WorkflowService instance backed by PostgreSQL."""
    return WorkflowService(dsn=postgres_dsn_workflow, behavior_service=mock_behavior_service)


@pytest.fixture
def sample_actor():
    """Sample actor for test operations."""
    return Actor(id="test-user", role="STRATEGIST", surface="CLI")


@pytest.fixture
def sample_steps():
    """Sample workflow steps."""
    return [
        TemplateStep(
            step_id="step-1",
            name="Analyze Request",
            description="Decompose the user request into sub-tasks",
            prompt_template="Analyze the following request:\n\n{{REQUEST}}\n\n{{BEHAVIORS}}",
            behavior_injection_point="{{BEHAVIORS}}",
            required_behaviors=["bhv-test001"],
        ),
        TemplateStep(
            step_id="step-2",
            name="Generate Plan",
            description="Create an execution plan",
            prompt_template="Based on the analysis, generate a plan:\n\n{{BEHAVIORS}}",
            behavior_injection_point="{{BEHAVIORS}}",
            required_behaviors=["bhv-test002"],
        ),
    ]


class TestWorkflowServiceCRUD:
    """Test template CRUD operations."""

    def test_create_template(self, workflow_service, sample_actor, sample_steps):
        """Test creating a workflow template."""
        template = workflow_service.create_template(
            name="Strategist Workflow",
            description="Decompose and plan tasks",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
            tags=["planning", "strategist"],
            metadata={"version": "1.0"},
        )

        assert template.template_id.startswith("wf-")
        assert template.name == "Strategist Workflow"
        assert template.role_focus == WorkflowRole.STRATEGIST
        assert len(template.steps) == 2
        assert template.created_by.id == "test-user"
        assert "planning" in template.tags

    def test_get_template(self, workflow_service, sample_actor, sample_steps):
        """Test retrieving a template by ID."""
        created = workflow_service.create_template(
            name="Test Template",
            description="Test description",
            role_focus=WorkflowRole.TEACHER,
            steps=sample_steps,
            actor=sample_actor,
        )

        retrieved = workflow_service.get_template(created.template_id)

        assert retrieved is not None
        assert retrieved.template_id == created.template_id
        assert retrieved.name == "Test Template"
        assert retrieved.role_focus == WorkflowRole.TEACHER
        assert len(retrieved.steps) == 2

    def test_get_nonexistent_template(self, workflow_service):
        """Test retrieving a template that doesn't exist."""
        result = workflow_service.get_template("wf-nonexistent")
        assert result is None

    def test_list_templates(self, workflow_service, sample_actor, sample_steps):
        """Test listing templates with filters."""
        # Create multiple templates
        workflow_service.create_template(
            name="Strategist Template",
            description="For strategists",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
            tags=["planning"],
        )
        workflow_service.create_template(
            name="Teacher Template",
            description="For teachers",
            role_focus=WorkflowRole.TEACHER,
            steps=sample_steps,
            actor=sample_actor,
            tags=["education"],
        )

        # List all
        all_templates = workflow_service.list_templates()
        assert len(all_templates) == 2

        # Filter by role
        strategist_templates = workflow_service.list_templates(role_focus=WorkflowRole.STRATEGIST)
        assert len(strategist_templates) == 1
        assert strategist_templates[0].role_focus == WorkflowRole.STRATEGIST

        # Filter by tags
        planning_templates = workflow_service.list_templates(tags=["planning"])
        assert len(planning_templates) == 1
        assert "planning" in planning_templates[0].tags


class TestBehaviorInjection:
    """Test behavior-conditioned inference integration."""

    def test_inject_behaviors(self, workflow_service, mock_behavior_service):
        """Test injecting behaviors into prompt templates."""
        prompt_template = "Analyze this task:\n\n{{BEHAVIORS}}\n\nProvide recommendations."
        behavior_ids = ["bhv-test001"]

        rendered, used = workflow_service.inject_behaviors(
            prompt_template=prompt_template,
            injection_point="{{BEHAVIORS}}",
            behavior_ids=behavior_ids,
        )

        assert "{{BEHAVIORS}}" not in rendered
        assert "behavior_test_pattern" in rendered
        assert "A test behavior for validation" in rendered
        assert used == ["bhv-test001"]
        mock_behavior_service.get_behavior.assert_called_once_with("bhv-test001")

    def test_inject_empty_behaviors(self, workflow_service):
        """Test injection with no behaviors."""
        prompt_template = "Task:\n\n{{BEHAVIORS}}\n\nEnd."
        rendered, used = workflow_service.inject_behaviors(
            prompt_template=prompt_template,
            injection_point="{{BEHAVIORS}}",
            behavior_ids=[],
        )

        assert "{{BEHAVIORS}}" not in rendered
        assert used == []
        assert rendered == "Task:\n\n\n\nEnd."


class TestWorkflowExecution:
    """Test workflow run creation and status tracking."""

    def test_run_workflow(self, workflow_service, sample_actor, sample_steps):
        """Test starting a workflow run."""
        template = workflow_service.create_template(
            name="Test Workflow",
            description="Test execution",
            role_focus=WorkflowRole.STUDENT,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
            behavior_ids=["bhv-test001"],
            metadata={"test": "run"},
        )

        assert run.run_id.startswith("run-")
        assert run.template_id == template.template_id
        assert run.template_name == "Test Workflow"
        assert run.role_focus == WorkflowRole.STUDENT
        assert run.status == WorkflowStatus.PENDING
        assert run.actor.id == "test-user"
        assert run.metadata["test"] == "run"

    def test_get_run(self, workflow_service, sample_actor, sample_steps):
        """Test retrieving a run by ID."""
        template = workflow_service.create_template(
            name="Test Template",
            description="Test",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
        )

        created_run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
        )

        retrieved_run = workflow_service.get_run(created_run.run_id)

        assert retrieved_run is not None
        assert retrieved_run.run_id == created_run.run_id
        assert retrieved_run.template_id == template.template_id

    def test_update_run_status(self, workflow_service, sample_actor, sample_steps):
        """Test updating run status and token count."""
        template = workflow_service.create_template(
            name="Test Template",
            description="Test",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
        )

        # Update to running
        workflow_service.update_run_status(
            run_id=run.run_id,
            status=WorkflowStatus.RUNNING,
            total_tokens=1500,
        )

        updated = workflow_service.get_run(run.run_id)
        assert updated.status == WorkflowStatus.RUNNING
        assert updated.total_tokens == 1500
        assert updated.completed_at is None

        # Update to completed
        workflow_service.update_run_status(
            run_id=run.run_id,
            status=WorkflowStatus.COMPLETED,
            total_tokens=3000,
        )

        final = workflow_service.get_run(run.run_id)
        assert final.status == WorkflowStatus.COMPLETED
        assert final.total_tokens == 3000
        assert final.completed_at is not None

    def test_run_nonexistent_template(self, workflow_service, sample_actor):
        """Test running a workflow with invalid template ID."""
        with pytest.raises(ValueError, match="Template not found"):
            workflow_service.run_workflow(
                template_id="wf-nonexistent",
                actor=sample_actor,
            )


class TestCLIAdapter:
    """Test CLI adapter parity."""

    def test_create_template_via_adapter(self, workflow_service):
        """Test creating a template through the CLI adapter."""
        adapter = CLIWorkflowServiceAdapter(workflow_service)

        steps_data = [
            {
                "step_id": "step-1",
                "name": "Plan",
                "description": "Create a plan",
                "prompt_template": "Create plan:\n\n{{BEHAVIORS}}",
                "behavior_injection_point": "{{BEHAVIORS}}",
                "required_behaviors": ["bhv-001"],
            }
        ]

        template = adapter.create_template(
            name="CLI Template",
            description="Created via CLI",
            role_focus="STRATEGIST",
            steps=steps_data,
            tags=["cli", "test"],
            metadata={"source": "cli"},
            actor_id="cli-user",
            actor_role="STRATEGIST",
        )

        assert template["name"] == "CLI Template"
        assert template["role_focus"] == "STRATEGIST"
        assert len(template["steps"]) == 1
        assert "cli" in template["tags"]

    def test_list_templates_via_adapter(self, workflow_service, sample_actor, sample_steps):
        """Test listing templates through adapter."""
        adapter = CLIWorkflowServiceAdapter(workflow_service)

        # Create a template
        workflow_service.create_template(
            name="Adapter Test",
            description="Test",
            role_focus=WorkflowRole.TEACHER,
            steps=sample_steps,
            actor=sample_actor,
        )

        templates = adapter.list_templates()
        assert len(templates) >= 1
        assert any(t["name"] == "Adapter Test" for t in templates)

    def test_run_workflow_via_adapter(self, workflow_service, sample_actor, sample_steps):
        """Test running a workflow through adapter."""
        adapter = CLIWorkflowServiceAdapter(workflow_service)

        template = workflow_service.create_template(
            name="Adapter Run Test",
            description="Test run",
            role_focus=WorkflowRole.STUDENT,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = adapter.run_workflow(
            template_id=template.template_id,
            behavior_ids=["bhv-001", "bhv-002"],
            metadata={"test": "adapter"},
            actor_id="cli-user",
            actor_role="STUDENT",
        )

        assert run["template_id"] == template.template_id
        assert run["status"] == "PENDING"
        assert run["actor"]["id"] == "cli-user"


class TestTelemetryIntegration:
    """Test telemetry event emission."""

    @patch("amprealize.workflow_service.emit_event")
    def test_create_template_emits_event(self, mock_emit, workflow_service, sample_actor, sample_steps):
        """Test that creating a template emits telemetry."""
        workflow_service.create_template(
            name="Telemetry Test",
            description="Test telemetry",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
        )

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "workflow.template.created"
        assert "template_id" in call_args[0][1]
        assert call_args[0][1]["role_focus"] == "STRATEGIST"

    @patch("amprealize.workflow_service.emit_event")
    def test_run_workflow_emits_events(self, mock_emit, workflow_service, sample_actor, sample_steps):
        """Test that running a workflow emits telemetry."""
        template = workflow_service.create_template(
            name="Run Telemetry Test",
            description="Test",
            role_focus=WorkflowRole.TEACHER,
            steps=sample_steps,
            actor=sample_actor,
        )
        mock_emit.reset_mock()

        workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
        )

        assert mock_emit.call_count == 2
        event_types = [call.args[0] for call in mock_emit.call_args_list]
        assert event_types[0] == "workflow.run.started"
        assert event_types[1] == "plan_created"
        plan_payload = mock_emit.call_args_list[1].args[1]
        assert plan_payload["template_id"] == template.template_id
        assert "baseline_tokens" in plan_payload

    @patch("amprealize.workflow_service.emit_event")
    def test_update_status_emits_event(self, mock_emit, workflow_service, sample_actor, sample_steps):
        """Test that status updates emit telemetry."""
        template = workflow_service.create_template(
            name="Status Telemetry Test",
            description="Test",
            role_focus=WorkflowRole.STUDENT,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
        )
        mock_emit.reset_mock()

        workflow_service.update_run_status(
            run_id=run.run_id,
            status=WorkflowStatus.COMPLETED,
            total_tokens=5000,
        )

        assert mock_emit.call_count == 1
        event_type = mock_emit.call_args.args[0]
        payload = mock_emit.call_args.args[1]
        assert event_type == "execution_update"
        assert payload["status"] == "COMPLETED"
        assert payload["output_tokens"] == 5000
        assert "baseline_tokens" in payload


class TestTokenAccounting:
    """Test token usage tracking for behavior reuse metrics."""

    def test_run_stores_token_count(self, workflow_service, sample_actor, sample_steps):
        """Test that runs track token counts."""
        template = workflow_service.create_template(
            name="Token Test",
            description="Test token tracking",
            role_focus=WorkflowRole.STRATEGIST,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
        )

        # Initial token count should be 0
        assert run.total_tokens == 0

        # Update with token count
        workflow_service.update_run_status(
            run_id=run.run_id,
            status=WorkflowStatus.COMPLETED,
            total_tokens=2500,
        )

        updated_run = workflow_service.get_run(run.run_id)
        assert updated_run.total_tokens == 2500
        assert updated_run.metadata.get("baseline_tokens") is not None

    def test_behavior_citation_tracking(self, workflow_service, sample_actor, sample_steps):
        """Test that runs track which behaviors were used."""
        template = workflow_service.create_template(
            name="Citation Test",
            description="Test behavior citations",
            role_focus=WorkflowRole.TEACHER,
            steps=sample_steps,
            actor=sample_actor,
        )

        run = workflow_service.run_workflow(
            template_id=template.template_id,
            actor=sample_actor,
            behavior_ids=["bhv-001", "bhv-002", "bhv-003"],
        )

        assert isinstance(run.behaviors_cited, list)
        assert set(run.behaviors_cited) >= {"bhv-001", "bhv-002", "bhv-003"}
        # Should also include required behaviors from template steps
        assert "bhv-test001" in run.behaviors_cited
        assert "bhv-test002" in run.behaviors_cited
