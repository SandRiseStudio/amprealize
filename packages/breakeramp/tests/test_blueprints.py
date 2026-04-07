"""Tests for blueprint utilities."""

import pytest
import yaml
from pathlib import Path

from breakeramp import Blueprint, ServiceSpec, get_blueprint_path, list_blueprints


class TestBlueprintUtilities:
    """Tests for blueprint helper functions."""

    def test_list_blueprints_returns_list(self):
        """list_blueprints returns a list."""
        blueprints = list_blueprints()
        assert isinstance(blueprints, list)

    def test_get_blueprint_path_packaged(self):
        """get_blueprint_path returns path for packaged blueprints."""
        # Get list of available blueprints
        blueprints = list_blueprints()

        if blueprints:
            # Try to get path for first blueprint
            first_id = blueprints[0]["id"] if isinstance(blueprints[0], dict) else blueprints[0]
            path = get_blueprint_path(first_id)
            if path:
                assert Path(path).exists()

    def test_get_blueprint_path_not_found(self):
        """get_blueprint_path returns None for non-existent blueprint."""
        path = get_blueprint_path("nonexistent-blueprint-12345")
        assert path is None


class TestBlueprintValidation:
    """Tests for blueprint validation logic."""

    def test_validate_valid_blueprint(self, sample_blueprint):
        """Valid blueprint passes validation."""
        errors = sample_blueprint.validate_topology()
        assert errors == []

    def test_validate_empty_services(self):
        """Blueprint with no services fails validation."""
        blueprint = Blueprint(
            name="empty",
            version="1.0",
            services={},
        )
        errors = blueprint.validate_topology()
        assert len(errors) > 0
        assert any("at least one service" in e.lower() for e in errors)

    def test_validate_invalid_port_format(self):
        """Blueprint with invalid port format fails validation."""
        blueprint = Blueprint(
            name="bad-ports",
            version="1.0",
            services={
                "web": ServiceSpec(
                    image="nginx:latest",
                    ports=["8080"],  # Missing container port
                ),
            },
        )
        errors = blueprint.validate_topology()
        assert any("port mapping" in e.lower() for e in errors)

    def test_validate_valid_port_formats(self):
        """Blueprint with valid port formats passes validation."""
        blueprint = Blueprint(
            name="good-ports",
            version="1.0",
            services={
                "web": ServiceSpec(
                    image="nginx:latest",
                    ports=["80:80", "443:443", "8080:80"],
                ),
            },
        )
        errors = blueprint.validate_topology()
        assert not any("port" in e.lower() for e in errors)

    def test_validate_service_name_with_hyphen(self):
        """Service names with hyphens are valid."""
        blueprint = Blueprint(
            name="hyphen-names",
            version="1.0",
            services={
                "redis-cache": ServiceSpec(image="redis:7"),
                "postgres-db": ServiceSpec(image="postgres:16"),
            },
        )
        errors = blueprint.validate_topology()
        assert not any("invalid characters" in e.lower() for e in errors)


class TestBlueprintSerialization:
    """Tests for blueprint serialization."""

    def test_blueprint_to_dict(self, sample_blueprint):
        """Blueprint can be serialized to dict."""
        data = sample_blueprint.model_dump()

        assert data["name"] == "test-blueprint"
        assert data["version"] == "1.0.0"
        assert "postgres" in data["services"]
        assert "redis" in data["services"]

    def test_blueprint_from_dict(self):
        """Blueprint can be created from dict."""
        data = {
            "name": "from-dict",
            "version": "2.0",
            "services": {
                "app": {
                    "image": "myapp:latest",
                    "ports": ["3000:3000"],
                },
            },
        }

        blueprint = Blueprint(**data)

        assert blueprint.name == "from-dict"
        assert blueprint.version == "2.0"
        assert "app" in blueprint.services

    def test_blueprint_to_yaml(self, sample_blueprint, tmp_path):
        """Blueprint can be serialized to YAML."""
        yaml_path = tmp_path / "blueprint.yaml"

        with open(yaml_path, "w") as f:
            yaml.dump(sample_blueprint.model_dump(), f)

        # Read back
        with open(yaml_path) as f:
            loaded = yaml.safe_load(f)

        assert loaded["name"] == sample_blueprint.name
        assert "postgres" in loaded["services"]

    def test_blueprint_from_yaml(self, tmp_path):
        """Blueprint can be loaded from YAML."""
        yaml_content = """
name: from-yaml
version: "1.0"
services:
  database:
    image: postgres:16
    ports:
      - "5432:5432"
    environment:
      POSTGRES_PASSWORD: secret
"""
        yaml_path = tmp_path / "test.yaml"
        yaml_path.write_text(yaml_content)

        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        blueprint = Blueprint(**data)

        assert blueprint.name == "from-yaml"
        assert blueprint.services["database"].image == "postgres:16"
        assert blueprint.services["database"].environment["POSTGRES_PASSWORD"] == "secret"
