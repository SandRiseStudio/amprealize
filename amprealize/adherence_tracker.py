"""AdherenceTracker — scores how well an agent followed injected behaviors per phase.

Tracks per-phase compliance by comparing injected behaviors/overlays against
actual citations in LLM output.  Builds PhaseAdherenceRecord per phase and
aggregates into an AdherenceResult for the full run.

Part of E3 — S3.9 Phase-Aware BCI (AMPREALIZE-277 / T3.9.4).
T3.4.3: Strict-mode policy checks for role declarations and mandatory guidance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

from amprealize.bci_contracts import (
    AdherenceResult,
    PhaseAdherenceRecord,
    PrependedBehavior,
    ValidateCitationsRequest,
)

logger = logging.getLogger(__name__)


class StrictModeViolation(Exception):
    """Raised when strict-mode policy checks detect a compliance failure.

    T3.4.3: Fail when required role declarations or mandatory guidance usage
    is absent in strict profiles.
    """

    def __init__(self, violations: List[str]) -> None:
        self.violations = violations
        msg = "; ".join(violations)
        super().__init__(f"Strict-mode violations: {msg}")


class AdherenceTracker:
    """Scores how well an agent followed injected behaviors per phase.

    Usage::

        tracker = AdherenceTracker(bci_service=bci, run_id="run-123")

        # After each phase's LLM response:
        tracker.record_phase(
            phase="PLANNING",
            output_text=llm_output,
            behaviors_injected=["behavior_a", "behavior_b"],
            overlays_injected=["overlay_security"],
        )

        # After all phases:
        result = tracker.finalize()
    """

    def __init__(
        self,
        *,
        bci_service: Any,  # BCIService — TYPE_CHECKING circular import avoidance
        run_id: str,
        telemetry: Any = None,
    ) -> None:
        self._bci = bci_service
        self._run_id = run_id
        self._telemetry = telemetry
        self._records: List[PhaseAdherenceRecord] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_phase(
        self,
        *,
        phase: str,
        output_text: str,
        behaviors_injected: Optional[List[str]] = None,
        overlays_injected: Optional[List[str]] = None,
    ) -> PhaseAdherenceRecord:
        """Score adherence for a single phase and store the record.

        Parameters
        ----------
        phase:
            GEP phase name (e.g. "PLANNING", "EXECUTING").
        output_text:
            The LLM output to analyse for citations.
        behaviors_injected:
            Behavior names that were injected for this phase.
        overlays_injected:
            Overlay names that were injected for this phase.

        Returns
        -------
        PhaseAdherenceRecord for the phase.
        """
        behaviors_injected = behaviors_injected or []
        overlays_injected = overlays_injected or []

        # Parse citations from output
        behaviors_cited: List[str] = []
        role_declared = False

        if self._bci and behaviors_injected:
            try:
                prepended = [
                    PrependedBehavior(behavior_name=name)
                    for name in behaviors_injected
                ]
                validation = self._bci.validate_citations(
                    ValidateCitationsRequest(
                        output_text=output_text,
                        prepended_behaviors=prepended,
                        minimum_citations=0,
                        allow_unlisted_behaviors=True,
                    )
                )
                behaviors_cited = [
                    c.behavior_name
                    for c in validation.valid_citations
                    if c.behavior_name
                ]
                role_declared = validation.role_declared
            except Exception as exc:
                logger.warning("Citation validation failed for phase %s: %s", phase, exc)

        # Determine cited/missed overlays via simple text matching
        overlays_cited = [
            o for o in overlays_injected if o.lower() in output_text.lower()
        ]
        overlays_missed = [o for o in overlays_injected if o not in overlays_cited]

        behaviors_missed = [b for b in behaviors_injected if b not in behaviors_cited]

        # Compute adherence score
        total_expected = len(behaviors_injected) + len(overlays_injected)
        total_cited = len(behaviors_cited) + len(overlays_cited)
        adherence_score = total_cited / max(total_expected, 1)

        violation_count = len(behaviors_missed) + len(overlays_missed)

        record = PhaseAdherenceRecord(
            phase=phase,
            behaviors_injected=behaviors_injected,
            behaviors_cited=behaviors_cited,
            behaviors_missed=behaviors_missed,
            overlays_injected=overlays_injected,
            overlays_cited=overlays_cited,
            overlays_missed=overlays_missed,
            role_declared=role_declared,
            adherence_score=round(adherence_score, 3),
            violation_count=violation_count,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        self._records.append(record)

        # T3.9.5: emit per-phase compliance telemetry
        self._emit_phase_telemetry(record)

        return record

    def finalize(self) -> AdherenceResult:
        """Aggregate all phase records into a run-level AdherenceResult."""
        total_injected = sum(len(r.behaviors_injected) for r in self._records)
        total_cited = sum(len(r.behaviors_cited) for r in self._records)
        total_violations = sum(r.violation_count for r in self._records)

        if self._records:
            overall_score = sum(r.adherence_score for r in self._records) / len(self._records)
        else:
            overall_score = 1.0

        result = AdherenceResult(
            run_id=self._run_id,
            phase_records=list(self._records),
            overall_adherence_score=round(overall_score, 3),
            total_behaviors_injected=total_injected,
            total_behaviors_cited=total_cited,
            total_violations=total_violations,
            is_compliant=total_violations == 0,
        )

        # T3.9.5: emit run-level adherence telemetry
        self._emit_run_telemetry(result)

        return result

    @property
    def records(self) -> List[PhaseAdherenceRecord]:
        """Return a copy of stored phase records."""
        return list(self._records)

    # ------------------------------------------------------------------
    # Strict-mode policy checks (T3.4.3)
    # ------------------------------------------------------------------

    def enforce_strict_mode(
        self,
        record: PhaseAdherenceRecord,
        *,
        strict_role_declaration: bool = False,
        strict_behavior_citation: bool = False,
        mandatory_overlays: Optional[List[str]] = None,
        raise_on_violation: bool = True,
    ) -> List[str]:
        """Check strict-mode policies for a phase record.

        When strict profile flags are active, this method verifies:
        - ``strict_role_declaration``: agent declared a role in its output
        - ``strict_behavior_citation``: every injected behavior was cited
        - ``mandatory_overlays``: all mandatory overlays were cited

        Parameters
        ----------
        record:
            The PhaseAdherenceRecord to check.
        strict_role_declaration:
            Require role declaration in output.
        strict_behavior_citation:
            Require all injected behaviors to be cited.
        mandatory_overlays:
            List of overlay names that must be cited.
        raise_on_violation:
            If True (default), raise StrictModeViolation on failures.
            If False, return list of violation messages (warnings).

        Returns
        -------
        List of violation message strings (empty if compliant).

        Raises
        ------
        StrictModeViolation
            When raise_on_violation=True and violations are detected.
        """
        violations: List[str] = []

        if strict_role_declaration and not record.role_declared:
            violations.append(
                f"Phase {record.phase}: role declaration required but absent"
            )

        if strict_behavior_citation and record.behaviors_missed:
            missed = ", ".join(record.behaviors_missed)
            violations.append(
                f"Phase {record.phase}: mandatory behaviors not cited: {missed}"
            )

        mandatory = mandatory_overlays or []
        for overlay in mandatory:
            if overlay not in record.overlays_cited:
                violations.append(
                    f"Phase {record.phase}: mandatory overlay not cited: {overlay}"
                )

        if violations:
            # Emit telemetry for strict-mode violations
            if self._telemetry:
                try:
                    self._telemetry.emit_event(
                        event_type="bci.strict_mode_violation",
                        payload={
                            "run_id": self._run_id,
                            "phase": record.phase,
                            "violations": violations,
                            "strict_role_declaration": strict_role_declaration,
                            "strict_behavior_citation": strict_behavior_citation,
                            "mandatory_overlays": mandatory,
                        },
                    )
                except Exception:
                    pass

            if raise_on_violation:
                raise StrictModeViolation(violations)
            else:
                for v in violations:
                    logger.warning("Strict-mode: %s", v)

        return violations

    def enforce_strict_mode_from_context(
        self,
        record: PhaseAdherenceRecord,
        context: Any,  # RuntimeContext
        *,
        raise_on_violation: bool = True,
    ) -> List[str]:
        """Convenience: extract strict flags from a RuntimeContext and enforce.

        Parameters
        ----------
        record:
            Phase adherence record to check.
        context:
            RuntimeContext with strict_role_declaration / strict_behavior_citation /
            mandatory_overlays flags.
        raise_on_violation:
            If True, raise on violation; if False, return warnings.
        """
        return self.enforce_strict_mode(
            record,
            strict_role_declaration=getattr(context, "strict_role_declaration", False),
            strict_behavior_citation=getattr(context, "strict_behavior_citation", False),
            mandatory_overlays=getattr(context, "mandatory_overlays", None),
            raise_on_violation=raise_on_violation,
        )

    # ------------------------------------------------------------------
    # Telemetry (T3.9.5)
    # ------------------------------------------------------------------

    def _emit_phase_telemetry(self, record: PhaseAdherenceRecord) -> None:
        """Emit per-phase adherence metrics."""
        if not self._telemetry:
            return
        try:
            self._telemetry.emit_event(
                event_type="bci.phase_adherence",
                payload={
                    "run_id": self._run_id,
                    "phase": record.phase,
                    "behaviors_injected": len(record.behaviors_injected),
                    "behaviors_cited": len(record.behaviors_cited),
                    "behaviors_missed": record.behaviors_missed,
                    "overlays_injected": len(record.overlays_injected),
                    "overlays_cited": len(record.overlays_cited),
                    "adherence_score": record.adherence_score,
                    "violation_count": record.violation_count,
                    "role_declared": record.role_declared,
                },
            )
        except Exception as exc:
            logger.debug("Failed to emit phase adherence telemetry: %s", exc)

    def _emit_run_telemetry(self, result: AdherenceResult) -> None:
        """Emit run-level adherence summary."""
        if not self._telemetry:
            return
        try:
            self._telemetry.emit_event(
                event_type="bci.run_adherence",
                payload={
                    "run_id": result.run_id,
                    "overall_adherence_score": result.overall_adherence_score,
                    "total_behaviors_injected": result.total_behaviors_injected,
                    "total_behaviors_cited": result.total_behaviors_cited,
                    "total_violations": result.total_violations,
                    "is_compliant": result.is_compliant,
                    "phases_tracked": len(result.phase_records),
                },
            )
        except Exception as exc:
            logger.debug("Failed to emit run adherence telemetry: %s", exc)

    def persist_analytics_events(self, result: Optional[AdherenceResult] = None) -> None:
        """Persist recommendation adoption, citation compliance, and missing-guidance events.

        Emits fine-grained analytics events suitable for aggregation in analytics
        tables (TimescaleDB continuous aggregates / DuckDB warehouse).

        T3.4.2: Store recommendation adoption, citation compliance, and
        missing-guidance events in analytics tables.
        """
        if not self._telemetry:
            return

        result = result or self.finalize()

        for record in result.phase_records:
            # Recommendation adoption: which injected behaviors were actually cited
            for name in record.behaviors_cited:
                try:
                    self._telemetry.emit_event(
                        event_type="analytics.recommendation_adoption",
                        payload={
                            "run_id": self._run_id,
                            "phase": record.phase,
                            "behavior_name": name,
                            "adopted": True,
                        },
                    )
                except Exception:
                    pass

            # Missing guidance: injected but not cited
            for name in record.behaviors_missed:
                try:
                    self._telemetry.emit_event(
                        event_type="analytics.missing_guidance",
                        payload={
                            "run_id": self._run_id,
                            "phase": record.phase,
                            "behavior_name": name,
                            "reason": "injected_but_not_cited",
                        },
                    )
                except Exception:
                    pass

            # Citation compliance per phase
            try:
                self._telemetry.emit_event(
                    event_type="analytics.citation_compliance",
                    payload={
                        "run_id": self._run_id,
                        "phase": record.phase,
                        "adherence_score": record.adherence_score,
                        "violation_count": record.violation_count,
                        "role_declared": record.role_declared,
                        "behaviors_injected": len(record.behaviors_injected),
                        "behaviors_cited": len(record.behaviors_cited),
                    },
                )
            except Exception:
                pass
