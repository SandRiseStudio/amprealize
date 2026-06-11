"""Cost alert email notification service with configurable templates.

Implements email-based cost alerts with dynamic templates for:
- Daily budget exceeded alerts
- Token usage spike alerts
- Cost anomaly alerts

Architecture:
- Template-based rendering with Jinja2
- SMTP transport with async sending support
- Configurable recipients and thresholds
- Alert cooldown to prevent fatigue

Usage:
    from amprealize.cost_alert_service import CostAlertService

    alert_service = CostAlertService()

    # Send budget alert
    alert_service.send_budget_exceeded_alert(
        current_spend=85.50,
        budget=80.00,
        period="daily"
    )

Behaviors referenced:
- behavior_use_raze_for_logging: Alert events logged via Raze
- behavior_externalize_configuration: Email config via settings
- behavior_validate_financial_impact: Cost tracking integration
"""

import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional
import logging
from string import Template


@dataclass
class EmailConfig:
    """SMTP email configuration."""
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    use_tls: bool = True
    use_ssl: bool = False
    from_address: str = "alerts@amprealize.local"
    from_name: str = "Amprealize Cost Alerts"

    @classmethod
    def from_settings(cls) -> "EmailConfig":
        """Load config from settings or environment."""
        import os
        return cls(
            smtp_host=os.getenv("SMTP_HOST", "localhost"),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=os.getenv("SMTP_PASSWORD"),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            use_ssl=os.getenv("SMTP_USE_SSL", "false").lower() == "true",
            from_address=os.getenv("SMTP_FROM_ADDRESS", "alerts@amprealize.local"),
            from_name=os.getenv("SMTP_FROM_NAME", "Amprealize Cost Alerts"),
        )


@dataclass
class AlertTemplate:
    """Email alert template with subject and body."""
    name: str
    subject_template: str
    body_template: str
    html_template: Optional[str] = None

    def render(self, context: Dict[str, Any]) -> tuple[str, str, Optional[str]]:
        """Render template with context variables.

        Returns:
            Tuple of (subject, body_text, body_html)
        """
        subject = Template(self.subject_template).safe_substitute(context)
        body = Template(self.body_template).safe_substitute(context)
        html = Template(self.html_template).safe_substitute(context) if self.html_template else None
        return subject, body, html


# Default alert templates
DEFAULT_TEMPLATES: Dict[str, AlertTemplate] = {
    "budget_exceeded": AlertTemplate(
        name="budget_exceeded",
        subject_template="[Amprealize Alert] Daily Budget Exceeded - $$current_spend USD",
        body_template="""
Amprealize Cost Alert - Daily Budget Exceeded

Current Spend: $$current_spend USD
Daily Budget: $$budget USD
Overage: $$overage USD ($overage_pct%)

Period: $period
Triggered At: $timestamp

Top Cost Drivers:
$cost_drivers

Recommendations:
1. Review high-usage endpoints and optimize prompts
2. Consider enabling request caching for repeated queries
3. Check for any unusual traffic patterns

---
This alert was sent by Amprealize Cost Monitoring.
To manage alert preferences, visit: $preferences_url
""",
        html_template="""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; }
        .alert-header { background: #dc3545; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .alert-body { background: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; border-radius: 0 0 8px 8px; }
        .metric { display: inline-block; background: white; padding: 15px; margin: 10px 0; border-radius: 8px; border: 1px solid #dee2e6; min-width: 150px; }
        .metric-value { font-size: 24px; font-weight: bold; color: #dc3545; }
        .metric-label { font-size: 12px; color: #6c757d; text-transform: uppercase; }
        .recommendations { background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 15px; margin-top: 20px; }
        .recommendations h4 { color: #856404; margin-top: 0; }
        .footer { font-size: 12px; color: #6c757d; margin-top: 20px; padding-top: 20px; border-top: 1px solid #dee2e6; }
    </style>
</head>
<body>
    <div class="alert-header">
        <h2>⚠️ Daily Budget Exceeded</h2>
        <p>Amprealize detected that your daily spending has exceeded the configured budget.</p>
    </div>
    <div class="alert-body">
        <div class="metric">
            <div class="metric-value">$$current_spend</div>
            <div class="metric-label">Current Spend</div>
        </div>
        <div class="metric">
            <div class="metric-value">$$budget</div>
            <div class="metric-label">Daily Budget</div>
        </div>
        <div class="metric">
            <div class="metric-value">$overage_pct%</div>
            <div class="metric-label">Over Budget</div>
        </div>

        <h3>Top Cost Drivers</h3>
        <p>$cost_drivers_html</p>

        <div class="recommendations">
            <h4>💡 Recommendations</h4>
            <ol>
                <li>Review high-usage endpoints and optimize prompts</li>
                <li>Consider enabling request caching for repeated queries</li>
                <li>Check for any unusual traffic patterns</li>
            </ol>
        </div>

        <div class="footer">
            <p>Triggered at: $timestamp</p>
            <p>This alert was sent by Amprealize Cost Monitoring.</p>
            <p><a href="$preferences_url">Manage alert preferences</a></p>
        </div>
    </div>
</body>
</html>
"""
    ),

    "token_spike": AlertTemplate(
        name="token_spike",
        subject_template="[Amprealize Alert] Token Usage Spike Detected - $spike_pct% Increase",
        body_template="""
Amprealize Cost Alert - Token Usage Spike

A significant increase in token usage has been detected.

Current Hour Usage: $current_tokens tokens
Previous Hour Usage: $previous_tokens tokens
Increase: $spike_pct%
Threshold: $threshold_pct%

Affected Endpoints:
$affected_endpoints

Triggered At: $timestamp

Action Required:
- Review recent requests for unusually long prompts
- Check for retry loops or duplicate requests
- Verify no runaway automation is causing excess usage

---
This alert was sent by Amprealize Cost Monitoring.
To manage alert preferences, visit: $preferences_url
""",
        html_template="""
<!DOCTYPE html>
<html>
<head>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; }
        .alert-header { background: #fd7e14; color: white; padding: 20px; border-radius: 8px 8px 0 0; }
        .alert-body { background: #f8f9fa; padding: 20px; border: 1px solid #dee2e6; border-radius: 0 0 8px 8px; }
        .metric { display: inline-block; background: white; padding: 15px; margin: 10px 0; border-radius: 8px; border: 1px solid #dee2e6; min-width: 150px; }
        .metric-value { font-size: 24px; font-weight: bold; color: #fd7e14; }
        .metric-label { font-size: 12px; color: #6c757d; text-transform: uppercase; }
        .footer { font-size: 12px; color: #6c757d; margin-top: 20px; padding-top: 20px; border-top: 1px solid #dee2e6; }
    </style>
</head>
<body>
    <div class="alert-header">
        <h2>📈 Token Usage Spike Detected</h2>
        <p>Token usage has increased significantly hour-over-hour.</p>
    </div>
    <div class="alert-body">
        <div class="metric">
            <div class="metric-value">$current_tokens</div>
            <div class="metric-label">Current Hour</div>
        </div>
        <div class="metric">
            <div class="metric-value">$previous_tokens</div>
            <div class="metric-label">Previous Hour</div>
        </div>
        <div class="metric">
            <div class="metric-value">+$spike_pct%</div>
            <div class="metric-label">Increase</div>
        </div>

        <h3>Affected Endpoints</h3>
        <p>$affected_endpoints_html</p>

        <div class="footer">
            <p>Triggered at: $timestamp</p>
            <p><a href="$preferences_url">Manage alert preferences</a></p>
        </div>
    </div>
</body>
</html>
"""
    ),

    "cost_anomaly": AlertTemplate(
        name="cost_anomaly",
        subject_template="[Amprealize Alert] Cost Anomaly Detected - $sigma_deviation σ Above Average",
        body_template="""
Amprealize Cost Alert - Anomaly Detected

Cost spending is significantly higher than your 7-day average.

Current Daily Spend: $$current_spend USD
7-Day Average: $$avg_spend USD
Standard Deviation: $$std_dev USD
Deviation: $sigma_deviation σ (Threshold: $threshold_sigma σ)

Anomaly Score: $anomaly_score

This could indicate:
- Unexpected high usage
- Pricing changes
- System misconfiguration

Triggered At: $timestamp

---
This alert was sent by Amprealize Cost Monitoring.
To manage alert preferences, visit: $preferences_url
""",
        html_template=None  # Use text template
    ),
}


@dataclass
class AlertCooldown:
    """Tracks alert cooldown periods to prevent alert fatigue."""
    cooldown_minutes: int = 60
    last_alerts: Dict[str, datetime] = field(default_factory=dict)

    def can_send(self, alert_type: str) -> bool:
        """Check if alert can be sent (not in cooldown)."""
        if alert_type not in self.last_alerts:
            return True
        elapsed = datetime.utcnow() - self.last_alerts[alert_type]
        return elapsed.total_seconds() >= (self.cooldown_minutes * 60)

    def record_sent(self, alert_type: str) -> None:
        """Record that an alert was sent."""
        self.last_alerts[alert_type] = datetime.utcnow()


class CostAlertService:
    """Service for sending cost-related email alerts."""

    def __init__(
        self,
        email_config: Optional[EmailConfig] = None,
        templates: Optional[Dict[str, AlertTemplate]] = None,
        recipients: Optional[List[str]] = None,
        cooldown_minutes: int = 60,
        enabled: bool = True,
        preferences_url: str = "http://localhost:8080/settings/alerts",
    ):
        """Initialize CostAlertService.

        Args:
            email_config: SMTP configuration (auto-loaded from env if None)
            templates: Custom alert templates (defaults used if None)
            recipients: Email recipients (from settings if None)
            cooldown_minutes: Minimum minutes between same alert type
            enabled: If False, no alerts are sent (for testing)
            preferences_url: URL for managing alert preferences
        """
        self.email_config = email_config or EmailConfig.from_settings()
        self.templates = templates or DEFAULT_TEMPLATES
        self.cooldown = AlertCooldown(cooldown_minutes=cooldown_minutes)
        self.enabled = enabled
        self.preferences_url = preferences_url
        self._logger = logging.getLogger(__name__)

        # Load recipients from settings or parameter
        if recipients:
            self.recipients = recipients
        else:
            self._load_recipients_from_settings()

    def _load_recipients_from_settings(self) -> None:
        """Load email recipients from CostOptimizationConfig."""
        try:
            from amprealize.config.settings import settings
            recipients_str = settings.cost.alert_email_recipients
            if recipients_str:
                self.recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
            else:
                self.recipients = []
        except ImportError:
            import os
            recipients_str = os.getenv("COST_ALERT_EMAIL_RECIPIENTS", "")
            self.recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]

    def send_budget_exceeded_alert(
        self,
        current_spend: float,
        budget: float,
        period: str = "daily",
        cost_drivers: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Send budget exceeded alert.

        Args:
            current_spend: Current period spend in USD
            budget: Budget threshold in USD
            period: Budget period (daily, weekly, monthly)
            cost_drivers: List of dicts with endpoint, tokens, cost

        Returns:
            True if alert was sent, False if skipped (cooldown/disabled)
        """
        alert_type = f"budget_exceeded_{period}"

        if not self._should_send(alert_type):
            return False

        overage = current_spend - budget
        overage_pct = round((overage / budget) * 100, 1)

        # Format cost drivers
        if cost_drivers:
            drivers_text = "\n".join([
                f"  • {d['endpoint']}: ${d['cost']:.2f} ({d['tokens']:,} tokens)"
                for d in cost_drivers[:5]
            ])
            drivers_html = "<ul>" + "".join([
                f"<li><strong>{d['endpoint']}</strong>: ${d['cost']:.2f} ({d['tokens']:,} tokens)</li>"
                for d in cost_drivers[:5]
            ]) + "</ul>"
        else:
            drivers_text = "  No detailed breakdown available"
            drivers_html = "<p>No detailed breakdown available</p>"

        context = {
            "current_spend": f"{current_spend:.2f}",
            "budget": f"{budget:.2f}",
            "overage": f"{overage:.2f}",
            "overage_pct": overage_pct,
            "period": period,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "cost_drivers": drivers_text,
            "cost_drivers_html": drivers_html,
            "preferences_url": self.preferences_url,
        }

        return self._send_alert("budget_exceeded", context)

    def send_token_spike_alert(
        self,
        current_tokens: int,
        previous_tokens: int,
        threshold_pct: float,
        affected_endpoints: Optional[List[str]] = None,
    ) -> bool:
        """Send token usage spike alert.

        Args:
            current_tokens: Tokens used in current hour
            previous_tokens: Tokens used in previous hour
            threshold_pct: Spike threshold percentage
            affected_endpoints: List of affected endpoint paths

        Returns:
            True if alert was sent, False if skipped
        """
        if not self._should_send("token_spike"):
            return False

        if previous_tokens == 0:
            spike_pct = 100.0  # First hour or no previous usage
        else:
            spike_pct = ((current_tokens - previous_tokens) / previous_tokens) * 100

        endpoints_text = "\n".join([f"  • {e}" for e in (affected_endpoints or ["Unknown"])])
        endpoints_html = "<ul>" + "".join([f"<li>{e}</li>" for e in (affected_endpoints or ["Unknown"])]) + "</ul>"

        context = {
            "current_tokens": f"{current_tokens:,}",
            "previous_tokens": f"{previous_tokens:,}",
            "spike_pct": f"{spike_pct:.1f}",
            "threshold_pct": f"{threshold_pct:.1f}",
            "affected_endpoints": endpoints_text,
            "affected_endpoints_html": endpoints_html,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "preferences_url": self.preferences_url,
        }

        return self._send_alert("token_spike", context)

    def send_cost_anomaly_alert(
        self,
        current_spend: float,
        avg_spend: float,
        std_dev: float,
        threshold_sigma: float,
    ) -> bool:
        """Send cost anomaly detection alert.

        Args:
            current_spend: Current daily spend in USD
            avg_spend: 7-day average spend in USD
            std_dev: Standard deviation of 7-day spend
            threshold_sigma: Configured sigma threshold

        Returns:
            True if alert was sent, False if skipped
        """
        if not self._should_send("cost_anomaly"):
            return False

        if std_dev == 0:
            sigma_deviation = 0.0
        else:
            sigma_deviation = (current_spend - avg_spend) / std_dev

        anomaly_score = round(min(1.0, sigma_deviation / 5.0), 2)  # Normalize to 0-1

        context = {
            "current_spend": f"{current_spend:.2f}",
            "avg_spend": f"{avg_spend:.2f}",
            "std_dev": f"{std_dev:.2f}",
            "sigma_deviation": f"{sigma_deviation:.2f}",
            "threshold_sigma": f"{threshold_sigma:.1f}",
            "anomaly_score": f"{anomaly_score:.2f}",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            "preferences_url": self.preferences_url,
        }

        return self._send_alert("cost_anomaly", context)

    def _should_send(self, alert_type: str) -> bool:
        """Check if alert should be sent."""
        if not self.enabled:
            self._logger.debug(f"Alert {alert_type} skipped: alerts disabled")
            return False

        if not self.recipients:
            self._logger.warning(f"Alert {alert_type} skipped: no recipients configured")
            return False

        if not self.cooldown.can_send(alert_type):
            self._logger.debug(f"Alert {alert_type} skipped: in cooldown period")
            return False

        return True

    def _send_alert(self, template_name: str, context: Dict[str, Any]) -> bool:
        """Send alert using template.

        Args:
            template_name: Name of template to use
            context: Template context variables

        Returns:
            True if sent successfully
        """
        if template_name not in self.templates:
            self._logger.error(f"Unknown alert template: {template_name}")
            return False

        template = self.templates[template_name]
        subject, body_text, body_html = template.render(context)

        try:
            success = self._send_email(subject, body_text, body_html)
            if success:
                self.cooldown.record_sent(template_name)
                self._log_alert_sent(template_name, context)
            return success
        except Exception as e:
            self._logger.exception(f"Failed to send {template_name} alert: {e}")
            return False

    def _send_email(
        self,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
    ) -> bool:
        """Send email via SMTP.

        Args:
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body

        Returns:
            True if sent successfully
        """
        config = self.email_config

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config.from_name} <{config.from_address}>"
        msg["To"] = ", ".join(self.recipients)

        # Attach text version
        msg.attach(MIMEText(body_text, "plain"))

        # Attach HTML version if provided
        if body_html:
            msg.attach(MIMEText(body_html, "html"))

        try:
            if config.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as server:
                    if config.smtp_user and config.smtp_password:
                        server.login(config.smtp_user, config.smtp_password)
                    server.sendmail(config.from_address, self.recipients, msg.as_string())
            else:
                with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
                    if config.use_tls:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                    if config.smtp_user and config.smtp_password:
                        server.login(config.smtp_user, config.smtp_password)
                    server.sendmail(config.from_address, self.recipients, msg.as_string())

            self._logger.info(f"Cost alert email sent to {len(self.recipients)} recipients")
            return True

        except smtplib.SMTPException as e:
            self._logger.error(f"SMTP error sending alert: {e}")
            return False

    def _log_alert_sent(self, alert_type: str, context: Dict[str, Any]) -> None:
        """Log alert event via Raze (if available)."""
        try:
            from amprealize.telemetry import TelemetryClient
            telemetry = TelemetryClient()
            telemetry.emit_event(
                event_type=f"cost.alert.{alert_type}",
                payload={
                    "alert_type": alert_type,
                    "recipients_count": len(self.recipients),
                    "context": {k: v for k, v in context.items() if k != "preferences_url"},
                }
            )
        except Exception:
            pass  # Telemetry failure shouldn't break alerts

    def add_template(self, template: AlertTemplate) -> None:
        """Add or replace an alert template.

        Args:
            template: AlertTemplate to add
        """
        self.templates[template.name] = template

    def set_recipients(self, recipients: List[str]) -> None:
        """Update email recipients.

        Args:
            recipients: List of email addresses
        """
        self.recipients = recipients

    def test_connection(self) -> bool:
        """Test SMTP connection.

        Returns:
            True if connection successful
        """
        config = self.email_config
        try:
            if config.use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context) as server:
                    if config.smtp_user and config.smtp_password:
                        server.login(config.smtp_user, config.smtp_password)
            else:
                with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
                    if config.use_tls:
                        server.starttls()
                    if config.smtp_user and config.smtp_password:
                        server.login(config.smtp_user, config.smtp_password)
            return True
        except Exception as e:
            self._logger.error(f"SMTP connection test failed: {e}")
            return False
