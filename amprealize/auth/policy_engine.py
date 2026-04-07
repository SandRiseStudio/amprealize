"""
Dynamic Policy Engine for Amprealize Agent Authorization.

Loads and evaluates authorization policies from YAML bundles with support for:
- Hot-reload via SIGHUP signal
- Role-based access control (RBAC) with inheritance
- Wildcard scope matching (e.g., 'behaviors:*')
- Condition evaluation (MFA, context attributes)
- First-match rule evaluation

References:
- docs/MCP_AUTH_IMPLEMENTATION_PLAN.md: Phase 7 specification
- docs/AGENT_AUTH_ARCHITECTURE.md: Policy contract
- schema/policy/agentauth/bundle.yaml: Production policy bundle
"""

from __future__ import annotations

import fnmatch
import logging
import os
import signal
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


# --- Policy Decision Types ---


class PolicyDecision(str, Enum):
    """Policy evaluation outcomes."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    CONSENT_REQUIRED = "CONSENT_REQUIRED"


class PolicyReason(str, Enum):
    """Structured reasons for policy decisions."""

    SCOPE_NOT_APPROVED = "SCOPE_NOT_APPROVED"
    POLICY_CONDITION_FAILED = "POLICY_CONDITION_FAILED"
    SECURITY_HOLD = "SECURITY_HOLD"
    MFA_REQUIRED = "MFA_REQUIRED"
    ROLE_NOT_AUTHORIZED = "ROLE_NOT_AUTHORIZED"
    CROSS_TENANT_DENIED = "CROSS_TENANT_DENIED"
    DEFAULT_DENY = "DEFAULT_DENY"
    EXPLICIT_ALLOW = "EXPLICIT_ALLOW"


@dataclass
class PolicyObligation:
    """Obligation attached to a policy decision."""

    type: str  # e.g., "notification", "mfa", "expiry", "audit"
    attributes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "attributes": dict(self.attributes)}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PolicyObligation:
        return cls(type=data.get("type", "unknown"), attributes=data.get("attributes", {}))


@dataclass
class PolicyResult:
    """Result of policy evaluation."""

    decision: PolicyDecision
    reason: PolicyReason
    matched_rule: Optional[str] = None
    obligations: List[PolicyObligation] = field(default_factory=list)
    bundle_version: Optional[str] = None
    evaluation_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "reason": self.reason.value,
            "matched_rule": self.matched_rule,
            "obligations": [o.to_dict() for o in self.obligations],
            "bundle_version": self.bundle_version,
            "evaluation_time_ms": self.evaluation_time_ms,
        }


@dataclass
class PolicyRule:
    """Parsed policy rule from YAML bundle."""

    id: str
    description: str
    effect: PolicyDecision
    match: Dict[str, Any]
    reason: Optional[PolicyReason] = None
    obligations: List[PolicyObligation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PolicyRule:
        """Parse rule from YAML dict."""
        effect_str = data.get("decision", "DENY")
        try:
            effect = PolicyDecision(effect_str)
        except ValueError:
            effect = PolicyDecision.DENY

        reason_str = data.get("reason")
        reason = None
        if reason_str:
            try:
                reason = PolicyReason(reason_str)
            except ValueError:
                reason = PolicyReason.POLICY_CONDITION_FAILED

        obligations = []
        for obl_data in data.get("obligations", []):
            obligations.append(PolicyObligation.from_dict(obl_data))

        return cls(
            id=data.get("id", "unknown"),
            description=data.get("description", ""),
            effect=effect,
            match=data.get("match", {}),
            reason=reason,
            obligations=obligations,
        )


@dataclass
class RoleDefinition:
    """Role with inheritance chain."""

    name: str
    description: str
    inherits: List[str] = field(default_factory=list)


@dataclass
class ScopeDefinition:
    """Scope catalog entry."""

    name: str
    description: str
    risk_level: str = "low"  # low, medium, high
    requires_mfa: bool = False


# --- Policy Engine ---


class PolicyEngine:
    """Dynamic YAML-based policy evaluation engine.

    Features:
    - Load policy bundles from YAML files
    - Hot-reload via SIGHUP signal
    - Role inheritance resolution
    - Wildcard scope matching
    - First-match rule evaluation
    - Thread-safe reload

    Usage:
        engine = PolicyEngine(bundle_path="/path/to/bundle.yaml")
        result = engine.evaluate(
            role="STUDENT",
            scope="behaviors:read",
            resource="behaviors/*",
            context={"mfa_verified": "true", "org_id": "org-123"}
        )
    """

    def __init__(
        self,
        bundle_path: Optional[str] = None,
        enable_hot_reload: bool = True,
        on_reload: Optional[Callable[[], None]] = None,
    ) -> None:
        """Initialize policy engine.

        Args:
            bundle_path: Path to YAML bundle file. Defaults to schema/policy/agentauth/bundle.yaml
            enable_hot_reload: Whether to register SIGHUP handler for hot reload
            on_reload: Optional callback invoked after successful reload
        """
        if bundle_path is None:
            # Default to project's policy bundle
            bundle_path = os.environ.get(
                "AMPREALIZE_POLICY_BUNDLE_PATH",
                str(Path(__file__).parent.parent.parent / "schema" / "policy" / "agentauth" / "bundle.yaml"),
            )

        self._bundle_path = Path(bundle_path)
        self._on_reload = on_reload
        self._lock = threading.RLock()

        # Policy state (protected by lock)
        self._rules: List[PolicyRule] = []
        self._roles: Dict[str, RoleDefinition] = {}
        self._scope_catalog: Dict[str, ScopeDefinition] = {}
        self._bundle_version: str = "unknown"
        self._loaded_at: Optional[datetime] = None

        # Load initial bundle
        self._load_bundle()

        # Register hot-reload signal handler
        if enable_hot_reload:
            self._register_reload_signal()

    @property
    def bundle_version(self) -> str:
        """Current bundle version."""
        with self._lock:
            return self._bundle_version

    @property
    def loaded_at(self) -> Optional[datetime]:
        """Timestamp when bundle was last loaded."""
        with self._lock:
            return self._loaded_at

    @property
    def rule_count(self) -> int:
        """Number of loaded rules."""
        with self._lock:
            return len(self._rules)

    def reload(self) -> bool:
        """Manually trigger bundle reload.

        Returns:
            True if reload succeeded, False otherwise
        """
        return self._load_bundle()

    def evaluate(
        self,
        role: str,
        scope: str,
        resource: Optional[str] = None,
        tool_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        """Evaluate policy for the given request.

        Uses first-match semantics - the first rule that matches determines the decision.

        Args:
            role: User/agent role (e.g., "ADMIN", "STRATEGIST", "STUDENT")
            scope: Requested scope (e.g., "behaviors:read", "actions.replay")
            resource: Optional resource identifier for resource-level policies
            tool_name: Optional MCP tool name for tool-specific rules
            context: Additional context (mfa_verified, org_id, project_id, etc.)

        Returns:
            PolicyResult with decision, reason, matched rule, and obligations
        """
        import time

        start_time = time.perf_counter()
        context = context or {}

        with self._lock:
            bundle_version = self._bundle_version
            rules = list(self._rules)  # Copy for thread safety
            roles = dict(self._roles)
            scope_catalog = dict(self._scope_catalog)

        # Resolve role inheritance
        effective_roles = self._resolve_role_hierarchy(role, roles)

        # Check scope catalog for MFA requirements
        scope_def = scope_catalog.get(scope) or scope_catalog.get(scope.replace(":", "."))
        mfa_required = scope_def.requires_mfa if scope_def else False

        # Handle mfa_verified as either bool or string
        mfa_verified_raw = context.get("mfa_verified", False)
        if isinstance(mfa_verified_raw, bool):
            mfa_verified = mfa_verified_raw
        else:
            mfa_verified = str(mfa_verified_raw).lower() == "true"

        # Add MFA status to context for rule evaluation
        context = dict(context)  # Copy to avoid mutation
        context["_mfa_required"] = mfa_required
        context["_mfa_verified"] = mfa_verified

        # Evaluate rules (first match wins)
        # Note: MFA enforcement is handled in rules, not here, so that
        # privileged roles (like Admin) can be granted access before
        # MFA checks via rule ordering.
        for rule in rules:
            if self._matches_rule(rule, effective_roles, scope, resource, tool_name, context):
                obligations = list(rule.obligations)

                # Add MFA obligation if scope requires it
                if mfa_required:
                    obligations.append(
                        PolicyObligation(type="mfa", attributes={"method": "TOTP"})
                    )

                reason = rule.reason
                if reason is None:
                    if rule.effect == PolicyDecision.ALLOW:
                        reason = PolicyReason.EXPLICIT_ALLOW
                    elif rule.effect == PolicyDecision.CONSENT_REQUIRED:
                        reason = PolicyReason.SCOPE_NOT_APPROVED
                    else:
                        reason = PolicyReason.POLICY_CONDITION_FAILED

                return PolicyResult(
                    decision=rule.effect,
                    reason=reason,
                    matched_rule=rule.id,
                    obligations=obligations,
                    bundle_version=bundle_version,
                    evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
                )

        # Default deny if no rules matched
        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=PolicyReason.DEFAULT_DENY,
            bundle_version=bundle_version,
            evaluation_time_ms=(time.perf_counter() - start_time) * 1000,
        )

    def preview(
        self,
        role: str,
        scopes: List[str],
        tool_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, PolicyResult]:
        """Preview policy decisions for multiple scopes.

        Useful for UI to show which operations will be allowed/denied.

        Args:
            role: User/agent role
            scopes: List of scopes to evaluate
            tool_name: Optional MCP tool name
            context: Additional context

        Returns:
            Dict mapping scope to PolicyResult
        """
        results = {}
        for scope in scopes:
            result = self.evaluate(
                role=role, scope=scope, tool_name=tool_name, context=context
            )
            results[scope] = result
        return results

    def get_allowed_scopes(
        self,
        role: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Set[str]:
        """Get all scopes allowed for a role.

        Args:
            role: User/agent role
            context: Additional context

        Returns:
            Set of allowed scope strings
        """
        allowed = set()
        with self._lock:
            for scope_name in self._scope_catalog.keys():
                result = self.evaluate(role=role, scope=scope_name, context=context)
                if result.decision == PolicyDecision.ALLOW:
                    allowed.add(scope_name)
        return allowed

    # --- Internal Methods ---

    def _load_bundle(self) -> bool:
        """Load policy bundle from YAML file.

        Returns:
            True if load succeeded, False otherwise
        """
        if not self._bundle_path.exists():
            logger.warning(f"Policy bundle not found: {self._bundle_path}")
            return False

        try:
            with open(self._bundle_path, "r", encoding="utf-8") as f:
                bundle = yaml.safe_load(f)

            if not bundle:
                logger.error("Empty policy bundle")
                return False

            # Parse bundle components
            new_version = bundle.get("bundle_version") or bundle.get("version", "unknown")
            new_rules = []
            new_roles = {}
            new_scopes = {}

            # Parse rules
            for rule_data in bundle.get("rules", []):
                try:
                    rule = PolicyRule.from_dict(rule_data)
                    new_rules.append(rule)
                except Exception as e:
                    logger.warning(f"Failed to parse rule {rule_data.get('id', 'unknown')}: {e}")

            # Parse roles
            for role_name, role_data in bundle.get("roles", {}).items():
                if isinstance(role_data, dict):
                    new_roles[role_name] = RoleDefinition(
                        name=role_name,
                        description=role_data.get("description", ""),
                        inherits=role_data.get("inherits", []),
                    )

            # Parse scope catalog
            for scope_name, scope_data in bundle.get("scope_catalog", {}).items():
                if isinstance(scope_data, dict):
                    new_scopes[scope_name] = ScopeDefinition(
                        name=scope_name,
                        description=scope_data.get("description", ""),
                        risk_level=scope_data.get("risk_level", "low"),
                        requires_mfa=scope_data.get("requires_mfa", False),
                    )

            # Atomically update state
            with self._lock:
                self._bundle_version = new_version
                self._rules = new_rules
                self._roles = new_roles
                self._scope_catalog = new_scopes
                self._loaded_at = datetime.utcnow()

            logger.info(
                f"Loaded policy bundle v{new_version} with {len(new_rules)} rules, "
                f"{len(new_roles)} roles, {len(new_scopes)} scopes"
            )

            # Invoke reload callback if provided
            if self._on_reload:
                try:
                    self._on_reload()
                except Exception as e:
                    logger.error(f"Reload callback failed: {e}")

            return True

        except yaml.YAMLError as e:
            logger.error(f"YAML parse error in policy bundle: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to load policy bundle: {e}")
            return False

    def _register_reload_signal(self) -> None:
        """Register SIGHUP handler for hot reload."""
        try:
            def reload_handler(signum: int, frame: Any) -> None:
                logger.info("Received SIGHUP, reloading policy bundle...")
                success = self._load_bundle()
                if success:
                    logger.info("Policy bundle reloaded successfully")
                else:
                    logger.error("Policy bundle reload failed")

            signal.signal(signal.SIGHUP, reload_handler)
            logger.debug("Registered SIGHUP handler for policy hot-reload")
        except (ValueError, OSError) as e:
            # Signal registration can fail in non-main threads or on Windows
            logger.debug(f"Could not register SIGHUP handler: {e}")

    def _resolve_role_hierarchy(
        self,
        role: str,
        roles: Dict[str, RoleDefinition],
    ) -> Set[str]:
        """Resolve role inheritance to get all effective roles.

        Args:
            role: Starting role name
            roles: Role definitions with inheritance

        Returns:
            Set of all effective roles (including inherited)
        """
        effective = set()
        to_process = [role.upper()]
        seen = set()

        while to_process:
            current = to_process.pop()
            if current in seen:
                continue
            seen.add(current)
            effective.add(current)

            # Add inherited roles
            role_def = roles.get(current)
            if role_def:
                for inherited in role_def.inherits:
                    if inherited.upper() not in seen:
                        to_process.append(inherited.upper())

        return effective

    def _matches_rule(
        self,
        rule: PolicyRule,
        effective_roles: Set[str],
        scope: str,
        resource: Optional[str],
        tool_name: Optional[str],
        context: Dict[str, Any],
    ) -> bool:
        """Check if a rule matches the request.

        Args:
            rule: PolicyRule to evaluate
            effective_roles: Set of roles (including inherited)
            scope: Requested scope
            resource: Optional resource identifier
            tool_name: Optional MCP tool name
            context: Request context

        Returns:
            True if rule matches, False otherwise
        """
        match = rule.match

        # Empty match = catch-all (default deny)
        if not match:
            return True

        # Check tool_name match
        if "tool_name" in match:
            rule_tool = match["tool_name"]
            if tool_name is None:
                return False
            if not self._wildcard_match(rule_tool, tool_name):
                return False

        # Check roles match
        if "roles" in match:
            rule_roles = {r.upper() for r in match["roles"]}
            if not effective_roles.intersection(rule_roles):
                return False

        # Check roles_excluded (role must NOT be in this list)
        if "roles_excluded" in match:
            excluded_roles = {r.upper() for r in match["roles_excluded"]}
            if effective_roles.intersection(excluded_roles):
                return False

        # Check scopes match
        if "scopes" in match:
            rule_scopes = match["scopes"]
            if isinstance(rule_scopes, str):
                rule_scopes = [rule_scopes]
            scope_matched = any(self._wildcard_match(rs, scope) for rs in rule_scopes)
            if not scope_matched:
                return False

        # Check resources match
        if "resources" in match:
            rule_resources = match["resources"]
            if isinstance(rule_resources, str):
                rule_resources = [rule_resources]
            if resource is None:
                # If rule requires specific resource but none provided, try match against "*"
                if "*" not in rule_resources:
                    return False
            else:
                resource_matched = any(
                    self._wildcard_match(rr, resource) for rr in rule_resources
                )
                if not resource_matched:
                    return False

        # Check MFA context
        if "mfa_verified" in match:
            expected_mfa = match["mfa_verified"]
            actual_mfa = context.get("mfa_verified", "false")
            if isinstance(actual_mfa, bool):
                actual_mfa = str(actual_mfa).lower()
            if isinstance(expected_mfa, bool):
                expected_mfa = str(expected_mfa).lower()
            if str(actual_mfa).lower() != str(expected_mfa).lower():
                return False

        # Check org_id context
        if "org_id" in match:
            if context.get("org_id") != match["org_id"]:
                return False

        # Check project_id context
        if "project_id" in match:
            if context.get("project_id") != match["project_id"]:
                return False

        return True

    def _wildcard_match(self, pattern: str, value: str) -> bool:
        """Match with wildcard support.

        Supports:
        - Exact match: "behaviors.read" matches "behaviors.read"
        - Wildcard suffix: "behaviors:*" matches "behaviors:read", "behaviors:write"
        - Full wildcard: "*" matches anything
        - fnmatch patterns: "behaviors.*" matches "behaviors.read"

        Args:
            pattern: Pattern to match against (may contain wildcards)
            value: Actual value to check

        Returns:
            True if pattern matches value
        """
        if pattern == "*":
            return True
        if pattern == value:
            return True

        # Normalize separators (support both : and .)
        pattern_normalized = pattern.replace(":", ".")
        value_normalized = value.replace(":", ".")

        if pattern_normalized == value_normalized:
            return True

        # fnmatch for glob-style patterns
        if "*" in pattern_normalized or "?" in pattern_normalized:
            return fnmatch.fnmatch(value_normalized, pattern_normalized)

        return False


# --- Singleton Access ---

_engine_instance: Optional[PolicyEngine] = None
_engine_lock = threading.Lock()


def get_policy_engine(
    bundle_path: Optional[str] = None,
    enable_hot_reload: bool = True,
) -> PolicyEngine:
    """Get or create the global PolicyEngine singleton.

    Args:
        bundle_path: Optional path to bundle (only used on first call)
        enable_hot_reload: Whether to enable SIGHUP hot-reload

    Returns:
        PolicyEngine singleton instance
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = PolicyEngine(
                    bundle_path=bundle_path,
                    enable_hot_reload=enable_hot_reload,
                )
    return _engine_instance


def reset_policy_engine() -> None:
    """Reset the singleton (for testing)."""
    global _engine_instance
    with _engine_lock:
        _engine_instance = None
