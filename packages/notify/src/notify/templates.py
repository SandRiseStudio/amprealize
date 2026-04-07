"""
Template engine for rendering notification content.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, BaseLoader, UndefinedError


@dataclass
class NotificationTemplate:
    """A notification template with subject, body, and optional HTML."""

    name: str
    subject_template: str
    body_template: str
    html_template: Optional[str] = None


class TemplateEngine:
    """
    Jinja2-based template engine for rendering notification content.

    Usage:
        engine = TemplateEngine()
        engine.register_template(NotificationTemplate(
            name="welcome",
            subject_template="Welcome {{ name }}!",
            body_template="Hi {{ name }}, welcome aboard.",
        ))

        result = engine.render("welcome", {"name": "Alice"})
        # result = {"subject": "Welcome Alice!", "body": "Hi Alice, welcome aboard.", "html_body": None}
    """

    def __init__(self, templates_dir: Optional[Path] = None):
        """
        Initialize the template engine.

        Args:
            templates_dir: Optional directory containing template files.
                          Structure: templates_dir/<template_name>/subject.txt, body.txt, body.html
        """
        self._templates: Dict[str, NotificationTemplate] = {}
        self._env = Environment(loader=BaseLoader())

        # Load templates from directory if provided
        if templates_dir:
            self._load_from_directory(templates_dir)

    def _load_from_directory(self, templates_dir: Path) -> None:
        """
        Load templates from a directory structure.

        Expected structure:
            templates_dir/
                invite/
                    subject.txt
                    body.txt
                    body.html (optional)
                welcome/
                    subject.txt
                    body.txt
        """
        templates_path = Path(templates_dir)
        if not templates_path.exists():
            return

        for template_dir in templates_path.iterdir():
            if template_dir.is_dir():
                name = template_dir.name

                subject_file = template_dir / "subject.txt"
                body_file = template_dir / "body.txt"
                html_file = template_dir / "body.html"

                if subject_file.exists() and body_file.exists():
                    subject_template = subject_file.read_text()
                    body_template = body_file.read_text()
                    html_template = html_file.read_text() if html_file.exists() else None

                    self.register_template(NotificationTemplate(
                        name=name,
                        subject_template=subject_template,
                        body_template=body_template,
                        html_template=html_template,
                    ))

    def register_template(self, template: NotificationTemplate) -> None:
        """
        Register a notification template.

        Args:
            template: The template to register.
        """
        self._templates[template.name] = template

    def get_template(self, name: str) -> Optional[NotificationTemplate]:
        """
        Get a registered template by name.

        Args:
            name: The template name.

        Returns:
            The template or None if not found.
        """
        return self._templates.get(name)

    def render(
        self,
        template_name: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Render a template with the given context.

        Args:
            template_name: Name of the registered template.
            context: Variables for template rendering.

        Returns:
            Dict with keys: subject, body, html_body (None if no HTML template).

        Raises:
            ValueError: If template not found.
        """
        template = self._templates.get(template_name)
        if not template:
            raise ValueError(f"Template not found: {template_name}")

        # Render each part
        subject = self._render_string(template.subject_template, context)
        body = self._render_string(template.body_template, context)
        html_body = None
        if template.html_template:
            html_body = self._render_string(template.html_template, context)

        return {
            "subject": subject,
            "body": body,
            "html_body": html_body,
        }

    def _render_string(self, template_str: str, context: Dict[str, Any]) -> str:
        """
        Render a template string with context.

        Missing variables are rendered as empty strings.
        """
        jinja_template = self._env.from_string(template_str)
        try:
            return jinja_template.render(**context)
        except UndefinedError:
            # Silently handle undefined variables
            return jinja_template.render(**context)
