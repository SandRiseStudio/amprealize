from __future__ import annotations

import json

import pytest

from amprealize.execution_observability import (
    ExecutionObservabilityContext,
    REDACTED_VALUE,
)
from amprealize.observability_contracts import (
    GenerationEnvelope,
    ObservabilityBackendProfile,
    ObservabilityCorrelation,
    ObservabilityDashboardSource,
    ObservabilityDataClass,
    ObservabilityRecordKind,
    ObservabilitySensitivity,
    ToolCallEnvelope,
    canonical_trace_examples,
    observability_backend_targets,
    observability_dashboard_sources,
    observability_retention_rules,
    observability_timescale_schema,
    retention_rule_for,
)

pytestmark = pytest.mark.unit


def test_correlation_can_be_built_from_execution_observability_context() -> None:
    context = ExecutionObservabilityContext(
        run_id="run-1",
        cycle_id="cycle-1",
        work_item_id="guideai-1111",
        project_id="proj-1",
        org_id="org-1",
        agent_id="agent-1",
        model_id="model-1",
        surface="chat",
        conversation_id="conv-1",
        message_id="msg-1",
        request_id="req-1",
        execution_mode="queued",
        source_type="chat",
        queue_job_id="job-1",
    )

    correlation = ObservabilityCorrelation.from_execution_context(
        context,
        trace_id="trace-1",
        span_id="span-1",
        actor_id="user-1",
        actor_role="Student",
        phase="executing",
    )

    assert correlation.to_dict() == {
        "trace_id": "trace-1",
        "span_id": "span-1",
        "org_id": "org-1",
        "project_id": "proj-1",
        "conversation_id": "conv-1",
        "message_id": "msg-1",
        "run_id": "run-1",
        "cycle_id": "cycle-1",
        "work_item_id": "guideai-1111",
        "actor_id": "user-1",
        "actor_role": "Student",
        "surface": "chat",
        "model_id": "model-1",
        "queue_job_id": "job-1",
        "phase": "executing",
    }


def test_generation_envelope_reports_required_correlation_gaps() -> None:
    record = GenerationEnvelope(
        record_id="gen-1",
        kind=ObservabilityRecordKind.GENERATION,
        name="llm.generation",
        timestamp="2026-04-28T00:00:00+00:00",
        correlation=ObservabilityCorrelation(
            trace_id="trace-1",
            span_id="span-1",
            project_id="proj-1",
            surface="chat",
        ),
    )

    assert record.missing_required_correlation() == ["model_id"]


def test_tool_call_envelope_sanitizes_export_payload() -> None:
    record = ToolCallEnvelope(
        record_id="tool-1",
        kind=ObservabilityRecordKind.TOOL_CALL,
        name="tool.workitems_update",
        timestamp="2026-04-28T00:00:00+00:00",
        correlation=ObservabilityCorrelation(
            trace_id="trace-1",
            span_id="span-1",
            project_id="proj-1",
            surface="mcp",
        ),
        sensitivity=ObservabilitySensitivity.RESTRICTED,
        tool_name="workitems_update",
        call_id="call-1",
        input_summary={"api_key": "secret-value", "item_id": "guideai-1111"},  # pragma: allowlist secret
        attributes={"raw_prompt": "token=super-secret-token"},
    )

    payload = record.to_sanitized_payload()

    assert payload["input_summary"]["api_key"] == REDACTED_VALUE
    assert payload["input_summary"]["item_id"] == "guideai-1111"
    assert payload["attributes"]["raw_prompt"] == f"token={REDACTED_VALUE}"
    json.dumps(payload)


def test_canonical_trace_examples_cover_all_record_kinds() -> None:
    examples = canonical_trace_examples()

    assert set(examples) == {kind.value for kind in ObservabilityRecordKind}
    assert examples["trace"]["correlation"]["trace_id"] == "trace-chat-run-1"
    assert examples["generation"]["model_id"] == "gpt-example"
    assert examples["behavior_candidate"]["candidate_id"] == "candidate-1"
    assert examples["behavior_candidate"]["source_trace_ids"] == ["trace-chat-run-1"]
    assert all(example["record_id"] for example in examples.values())
    json.dumps(examples)


def test_canonical_observability_envelope_json_schema_validates_examples() -> None:
    import json
    from pathlib import Path

    import jsonschema

    schema_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "contracts"
        / "schemas"
        / "canonical_observability_envelope.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    examples = canonical_trace_examples()
    for kind, payload in examples.items():
        validator.validate(payload)

    bad_generation = {
        **examples["generation"],
        "correlation": {k: v for k, v in examples["generation"]["correlation"].items() if k != "model_id"},
    }
    with pytest.raises(jsonschema.exceptions.ValidationError):
        validator.validate(bad_generation)


def test_backend_targets_cover_all_profiles_and_record_kinds() -> None:
    targets = observability_backend_targets()
    expected_record_kinds = [kind.value for kind in ObservabilityRecordKind]

    assert set(targets) == {profile.value for profile in ObservabilityBackendProfile}
    for profile_targets in targets.values():
        assert profile_targets["record_kinds"] == expected_record_kinds

    assert targets["oss"]["primary_store"] == "postgres"
    assert targets["self_hosted_enterprise"]["dashboard"] == "metabase"
    assert targets["managed_enterprise"]["trace_export"] == "datadog"
    assert targets["managed_enterprise"]["llm_trace_export"] == "langfuse_cloud"
    json.dumps(targets)


def test_timescale_schema_contract_covers_canonical_storage_and_dashboards() -> None:
    schema = observability_timescale_schema()

    assert schema["hypertables"] == ["observability_records"]
    assert "observability_generations" in schema["tables"]
    assert "observability_tool_calls" in schema["tables"]
    assert "observability_actions" in schema["tables"]
    assert "observability_outcomes" in schema["tables"]
    assert "observability_retention_policies" in schema["tables"]
    assert "observability_trace_summary" in schema["views"]
    assert "observability_generation_metrics" in schema["views"]
    assert "observability_behavior_candidate_lifecycle" in schema["views"]
    assert "observability_span_tree" in schema["views"]
    assert "observability_run_summary" in schema["views"]
    assert "observability_conversation_summary" in schema["views"]
    assert schema["projection_tables"] == {
        "generation": "observability_generations",
        "tool_call": "observability_tool_calls",
        "action": "observability_actions",
        "outcome": "observability_outcomes",
    }
    assert schema["migration_revision"] == "20260505_observability_analytics"
    assert schema["record_table"]["primary_key"] == ["record_id", "record_timestamp"]
    assert {"trace_id", "span_id", "payload", "data_class", "retention_until"}.issubset(
        schema["record_table"]["required_columns"]
    )
    json.dumps(schema)


def test_dashboard_sources_wire_metabase_and_looker_datasets() -> None:
    sources = observability_dashboard_sources()

    assert set(sources) == {
        ObservabilityDashboardSource.METABASE.value,
        ObservabilityDashboardSource.LOOKER.value,
    }

    metabase = sources["metabase"]
    assert metabase["backend_profile"] == ObservabilityBackendProfile.SELF_HOSTED_ENTERPRISE.value
    assert "AMPREALIZE_TELEMETRY_PG_DSN" in metabase["connection_env"]
    assert metabase["trace_drilldown_url_template"] == "/work-items/{work_item_id}?trace_id={trace_id}"
    assert {dataset["source"] for dataset in metabase["datasets"]} == {
        "observability_trace_summary",
        "observability_generation_metrics",
        "observability_tool_performance",
        "observability_business_outcomes",
        "observability_behavior_candidate_lifecycle",
        "observability_span_tree",
        "observability_run_summary",
        "observability_conversation_summary",
    }
    generation_dataset = next(
        dataset for dataset in metabase["datasets"] if dataset["name"] == "generation_metrics"
    )
    assert "cost_usd" in generation_dataset["measures"]
    assert "avg_first_token_latency_ms" in generation_dataset["measures"]
    lifecycle_dataset = next(
        dataset for dataset in metabase["datasets"] if dataset["name"] == "behavior_candidate_lifecycle"
    )
    assert {"approval_rate", "estimated_token_savings", "decayed_behavior_count"}.issubset(
        lifecycle_dataset["measures"]
    )
    assert "rejection_reason" in lifecycle_dataset["dimensions"]

    looker = sources["looker"]
    assert looker["backend_profile"] == ObservabilityBackendProfile.MANAGED_ENTERPRISE.value
    assert "AMPREALIZE_ENTERPRISE_WAREHOUSE_DSN" in looker["connection_env"]
    assert "app.datadoghq.com/apm/trace/{trace_id}" in looker["trace_drilldown_url_template"]
    assert all(
        dataset["source"].startswith("enterprise_warehouse.")
        for dataset in looker["datasets"]
    )
    trace_dataset = next(
        dataset for dataset in looker["datasets"] if dataset["name"] == "observability_trace_summary"
    )
    assert {"datadog_trace_url", "langfuse_trace_url"}.issubset(trace_dataset["dimensions"])
    assert {"datadog_trace_url", "langfuse_trace_url"}.issubset(
        trace_dataset["drilldown_fields"]
    )
    looker_lifecycle_dataset = next(
        dataset
        for dataset in looker["datasets"]
        if dataset["name"] == "observability_behavior_candidate_lifecycle"
    )
    assert "candidate_rejected_count" in looker_lifecycle_dataset["measures"]
    assert "rejection_reason" in looker_lifecycle_dataset["drilldown_fields"]
    json.dumps(sources)


def test_backend_targets_expose_dashboard_dataset_names() -> None:
    targets = observability_backend_targets()

    assert targets["self_hosted_enterprise"]["dashboard_sources"] == ["metabase"]
    assert targets["self_hosted_enterprise"]["dashboard_datasets"] == [
        "trace_summary",
        "generation_metrics",
        "tool_performance",
        "business_outcomes",
        "behavior_candidate_lifecycle",
        "span_tree",
        "run_summary",
        "conversation_summary",
    ]
    assert targets["managed_enterprise"]["dashboard_sources"] == ["looker"]
    assert targets["managed_enterprise"]["dashboard_datasets"] == [
        "observability_trace_summary",
        "observability_generation_metrics",
        "observability_tool_performance",
        "observability_business_outcomes",
        "observability_behavior_candidate_lifecycle",
        "observability_span_tree",
        "observability_run_summary",
        "observability_conversation_summary",
    ]


def test_retention_rules_cover_expected_data_classes() -> None:
    rules = observability_retention_rules()

    assert set(rules) == {data_class.value for data_class in ObservabilityDataClass}
    assert rules["metadata_trace"]["sensitivity"] == ObservabilitySensitivity.METADATA.value
    assert rules["raw_prompt"]["sensitivity"] == ObservabilitySensitivity.RAW.value
    assert rules["tool_args"]["sensitivity"] == ObservabilitySensitivity.RESTRICTED.value
    assert rules["behavior_mining_feature"]["default_retention_days"] > rules["raw_response"]["default_retention_days"]
    assert rules["hash"]["purge_action"] == "retain_non_reversible_hash"
    json.dumps(rules)


def test_retention_rule_for_supports_enum_and_string_values() -> None:
    raw_prompt_rule = retention_rule_for(ObservabilityDataClass.RAW_PROMPT)
    output_preview_rule = retention_rule_for("output_preview")

    assert raw_prompt_rule["allowed_access_tiers"] == ["admin", "compliance"]
    assert output_preview_rule["max_retention_days"] == 90
    assert output_preview_rule["purge_action"] == "delete"
