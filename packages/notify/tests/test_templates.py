"""
Tests for template engine.
"""

import pytest
from pathlib import Path

from notify.templates import TemplateEngine, NotificationTemplate


class TestNotificationTemplate:
    """Tests for NotificationTemplate dataclass."""

    def test_create_template(self):
        """Test creating a notification template."""
        template = NotificationTemplate(
            name="test_template",
            subject_template="Hello {{ name }}",
            body_template="Welcome to {{ org }}, {{ name }}!",
        )

        assert template.name == "test_template"
        assert template.subject_template == "Hello {{ name }}"
        assert template.body_template == "Welcome to {{ org }}, {{ name }}!"
        assert template.html_template is None

    def test_create_template_with_html(self):
        """Test creating a template with HTML."""
        template = NotificationTemplate(
            name="html_template",
            subject_template="Subject",
            body_template="Plain text body",
            html_template="<p>HTML body</p>",
        )

        assert template.html_template == "<p>HTML body</p>"


class TestTemplateEngine:
    """Tests for TemplateEngine."""

    @pytest.fixture
    def engine(self):
        """Create a template engine."""
        return TemplateEngine()

    def test_register_template(self, engine):
        """Test registering a template."""
        template = NotificationTemplate(
            name="test",
            subject_template="Subject",
            body_template="Body",
        )
        engine.register_template(template)

        assert "test" in engine._templates

    def test_get_template(self, engine):
        """Test getting a registered template."""
        template = NotificationTemplate(
            name="test",
            subject_template="Subject",
            body_template="Body",
        )
        engine.register_template(template)

        retrieved = engine.get_template("test")
        assert retrieved == template

    def test_get_template_not_found(self, engine):
        """Test getting a template that doesn't exist."""
        assert engine.get_template("nonexistent") is None

    def test_render_template(self, engine):
        """Test rendering a template with context."""
        template = NotificationTemplate(
            name="welcome",
            subject_template="Welcome {{ name }}!",
            body_template="Hi {{ name }}, welcome to {{ org }}.",
        )
        engine.register_template(template)

        result = engine.render("welcome", {"name": "Alice", "org": "Acme"})

        assert result["subject"] == "Welcome Alice!"
        assert result["body"] == "Hi Alice, welcome to Acme."
        assert result["html_body"] is None

    def test_render_template_with_html(self, engine):
        """Test rendering a template with HTML."""
        template = NotificationTemplate(
            name="html_welcome",
            subject_template="Welcome",
            body_template="Plain text",
            html_template="<h1>Welcome {{ name }}</h1>",
        )
        engine.register_template(template)

        result = engine.render("html_welcome", {"name": "Bob"})

        assert result["subject"] == "Welcome"
        assert result["body"] == "Plain text"
        assert result["html_body"] == "<h1>Welcome Bob</h1>"

    def test_render_missing_template(self, engine):
        """Test rendering a template that doesn't exist."""
        with pytest.raises(ValueError, match="Template not found"):
            engine.render("nonexistent", {})

    def test_render_with_missing_variable(self, engine):
        """Test rendering with missing variable (Jinja2 uses empty string)."""
        template = NotificationTemplate(
            name="test",
            subject_template="Hello {{ name }}",
            body_template="Welcome {{ missing_var }}!",
        )
        engine.register_template(template)

        # Jinja2 with UndefinedSilent renders missing vars as empty
        result = engine.render("test", {"name": "Alice"})
        assert result["subject"] == "Hello Alice"
        # missing_var should be empty string
        assert result["body"] == "Welcome !"


class TestTemplateEngineWithFiles:
    """Tests for loading templates from files."""

    @pytest.fixture
    def templates_dir(self, tmp_path):
        """Create a temporary templates directory."""
        # Create invite template
        invite_dir = tmp_path / "invite"
        invite_dir.mkdir()
        (invite_dir / "subject.txt").write_text("Invitation to {{ org_name }}")
        (invite_dir / "body.txt").write_text("You've been invited to join {{ org_name }}!")
        (invite_dir / "body.html").write_text("<p>You've been invited to join <b>{{ org_name }}</b>!</p>")

        return tmp_path

    def test_load_from_directory(self, templates_dir):
        """Test loading templates from directory."""
        engine = TemplateEngine(templates_dir=templates_dir)

        # Should have loaded invite template
        template = engine.get_template("invite")
        assert template is not None
        assert "{{ org_name }}" in template.subject_template
        assert "{{ org_name }}" in template.body_template
        assert "{{ org_name }}" in template.html_template

    def test_render_loaded_template(self, templates_dir):
        """Test rendering a template loaded from files."""
        engine = TemplateEngine(templates_dir=templates_dir)

        result = engine.render("invite", {"org_name": "Acme Corp"})

        assert result["subject"] == "Invitation to Acme Corp"
        assert result["body"] == "You've been invited to join Acme Corp!"
        assert "<b>Acme Corp</b>" in result["html_body"]
