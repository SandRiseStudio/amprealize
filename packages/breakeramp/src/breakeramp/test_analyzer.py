"""Test Dependency Analyzer for BreakerAmp.

This module provides intelligent analysis of test files to determine
which infrastructure services they require. It supports:

1. AST-based parsing to discover pytest markers
2. Fixture dependency tracking
3. Import analysis for service detection
4. Configuration-based fallback mappings

Usage:
    from breakeramp.test_analyzer import TestDependencyAnalyzer
    from breakeramp import Blueprint

    analyzer = TestDependencyAnalyzer()
    blueprint = Blueprint(...)

    # Analyze test files
    result = analyzer.analyze_tests(
        test_paths=["tests/integration/test_api.py"],
        blueprint=blueprint,
    )

    print(f"Required services: {result.required_services}")
    print(f"Discovered markers: {result.discovered_markers}")
"""

import ast
import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .models import Blueprint, TestSuiteDefinition


@dataclass
class TestAnalysisResult:
    """Result from analyzing test files.

    Attributes:
        discovered_markers: All pytest markers found in test files
        discovered_fixtures: All fixture names used in test files
        required_services: Services determined to be required
        service_sources: Map of service name to why it was included
        test_files_analyzed: Number of test files analyzed
        analysis_errors: Any errors encountered during analysis
    """
    discovered_markers: Set[str] = field(default_factory=set)
    discovered_fixtures: Set[str] = field(default_factory=set)
    required_services: Set[str] = field(default_factory=set)
    service_sources: Dict[str, str] = field(default_factory=dict)
    test_files_analyzed: int = 0
    analysis_errors: List[str] = field(default_factory=list)

    def add_service(self, service: str, source: str) -> None:
        """Add a required service with its source reason."""
        self.required_services.add(service)
        if service not in self.service_sources:
            self.service_sources[service] = source
        else:
            # Append additional source
            self.service_sources[service] += f"; {source}"


class MarkerVisitor(ast.NodeVisitor):
    """AST visitor to extract pytest markers and fixtures from test files."""

    def __init__(self) -> None:
        self.markers: Set[str] = set()
        self.fixtures: Set[str] = set()
        self.imports: Set[str] = set()
        self.function_names: Set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visit function definitions to find test functions and their decorators."""
        # Check if it's a test function
        if node.name.startswith("test_") or node.name.startswith("Test"):
            self.function_names.add(node.name)

            # Extract markers from decorators
            for decorator in node.decorator_list:
                self._extract_marker(decorator)

            # Extract fixture arguments
            for arg in node.args.args:
                fixture_name = arg.arg
                # Skip 'self' and common non-fixture args
                if fixture_name not in ("self", "cls", "request", "pytestconfig"):
                    self.fixtures.add(fixture_name)

        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Handle async test functions the same way."""
        # Treat async functions same as regular functions for marker/fixture extraction
        if node.name.startswith("test_") or node.name.startswith("Test"):
            self.function_names.add(node.name)

            for decorator in node.decorator_list:
                self._extract_marker(decorator)

            for arg in node.args.args:
                fixture_name = arg.arg
                if fixture_name not in ("self", "cls", "request", "pytestconfig"):
                    self.fixtures.add(fixture_name)

        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Visit class definitions to find test classes and their decorators."""
        if node.name.startswith("Test"):
            for decorator in node.decorator_list:
                self._extract_marker(decorator)

        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Track imports for service detection."""
        for alias in node.names:
            self.imports.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Track from imports for service detection."""
        if node.module:
            self.imports.add(node.module)
        self.generic_visit(node)

    def _extract_marker(self, decorator: ast.expr) -> None:
        """Extract pytest marker from a decorator node."""
        # Handle @pytest.mark.marker_name
        if isinstance(decorator, ast.Attribute):
            if isinstance(decorator.value, ast.Attribute):
                if (
                    hasattr(decorator.value, "attr")
                    and decorator.value.attr == "mark"
                ):
                    self.markers.add(decorator.attr)

        # Handle @pytest.mark.marker_name(...)
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Attribute):
                func = decorator.func
                if isinstance(func.value, ast.Attribute):
                    if hasattr(func.value, "attr") and func.value.attr == "mark":
                        self.markers.add(func.attr)

                # Handle @marker (direct decorator, e.g., from conftest)
                elif hasattr(func, "attr"):
                    # Could be a custom marker or fixture decorator
                    attr_name = func.attr
                    if attr_name not in (
                        "fixture",
                        "parametrize",
                        "skip",
                        "skipif",
                        "xfail",
                    ):
                        self.markers.add(attr_name)


class TestDependencyAnalyzer:
    """Analyzes test files to determine required infrastructure services.

    The analyzer uses multiple strategies to determine service requirements:

    1. **AST Parsing**: Extracts pytest markers from test file decorators
    2. **Blueprint Matching**: Maps markers to services via blueprint test_markers
    3. **Suite Config**: Uses explicit marker/file mappings from TestSuiteDefinition
    4. **Import Heuristics**: Detects service needs from import statements

    Example:
        analyzer = TestDependencyAnalyzer()

        # With blueprint (uses test_markers on services)
        result = analyzer.analyze_tests(
            test_paths=["tests/integration/"],
            blueprint=my_blueprint,
        )

        # With explicit suite config
        suite = TestSuiteDefinition(
            name="my-suite",
            marker_mappings=[
                TestServiceMapping(marker="db", services=["postgres"]),
            ],
        )
        result = analyzer.analyze_tests(
            test_paths=["tests/"],
            suite_config=suite,
        )
    """

    # Default marker-to-service mappings as fallback
    DEFAULT_MARKER_SERVICES: Dict[str, List[str]] = {
        # Database markers
        "db": ["postgres", "database"],
        "postgres": ["postgres", "postgres-db", "telemetry-db"],
        "timescaledb": ["timescaledb", "telemetry-db", "metrics-db"],
        "redis": ["redis", "redis-cache"],
        "kafka": ["kafka", "zookeeper"],
        "mongo": ["mongodb", "mongo"],
        "mysql": ["mysql", "mysql-db"],
        # Integration markers
        "integration": [],  # Usually means "full stack" - handled separately
        "e2e": [],
        "slow": [],
        # Service-specific markers
        "api": ["api-server"],
        "web": ["web-server", "frontend"],
        "worker": ["worker", "celery-worker"],
    }

    # Import patterns that suggest service requirements
    IMPORT_PATTERNS: Dict[str, List[str]] = {
        r"psycopg|asyncpg|sqlalchemy": ["postgres"],
        r"redis|aioredis": ["redis"],
        r"kafka|aiokafka|confluent_kafka": ["kafka"],
        r"pymongo|motor": ["mongodb"],
        r"elasticsearch": ["elasticsearch"],
        r"celery": ["redis", "worker"],
    }

    def __init__(
        self,
        default_marker_services: Optional[Dict[str, List[str]]] = None,
        import_patterns: Optional[Dict[str, List[str]]] = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            default_marker_services: Override default marker-to-service mappings
            import_patterns: Override default import pattern detection
        """
        self.marker_services = default_marker_services or self.DEFAULT_MARKER_SERVICES.copy()
        self.import_patterns = import_patterns or self.IMPORT_PATTERNS.copy()

    def analyze_tests(
        self,
        test_paths: List[str],
        blueprint: Optional[Blueprint] = None,
        suite_config: Optional[TestSuiteDefinition] = None,
        markers: Optional[List[str]] = None,
        use_import_heuristics: bool = True,
    ) -> TestAnalysisResult:
        """Analyze test files and determine required services.

        Args:
            test_paths: List of test file paths or directories
            blueprint: Blueprint to use for marker-to-service mapping
            suite_config: Explicit test suite configuration
            markers: Additional markers to include (beyond discovered ones)
            use_import_heuristics: Whether to analyze imports for service hints

        Returns:
            TestAnalysisResult with discovered markers and required services
        """
        result = TestAnalysisResult()

        # Add explicit markers
        if markers:
            result.discovered_markers.update(markers)

        # Analyze each test path
        for test_path in test_paths:
            path = Path(test_path)
            if path.is_file():
                self._analyze_file(path, result, use_import_heuristics)
            elif path.is_dir():
                self._analyze_directory(path, result, use_import_heuristics)
            else:
                result.analysis_errors.append(f"Path not found: {test_path}")

        # Map markers to services
        self._resolve_services(result, blueprint, suite_config)

        return result

    def _analyze_file(
        self,
        file_path: Path,
        result: TestAnalysisResult,
        use_import_heuristics: bool,
    ) -> None:
        """Analyze a single test file."""
        if not file_path.suffix == ".py":
            return

        try:
            source = file_path.read_text()
            tree = ast.parse(source, filename=str(file_path))

            visitor = MarkerVisitor()
            visitor.visit(tree)

            result.discovered_markers.update(visitor.markers)
            result.discovered_fixtures.update(visitor.fixtures)
            result.test_files_analyzed += 1

            # Import heuristics
            if use_import_heuristics:
                self._analyze_imports(visitor.imports, result, str(file_path))

        except SyntaxError as e:
            result.analysis_errors.append(f"Syntax error in {file_path}: {e}")
        except Exception as e:
            result.analysis_errors.append(f"Error analyzing {file_path}: {e}")

    def _analyze_directory(
        self,
        dir_path: Path,
        result: TestAnalysisResult,
        use_import_heuristics: bool,
    ) -> None:
        """Recursively analyze a directory of test files."""
        for file_path in dir_path.rglob("*.py"):
            # Skip __pycache__ and other non-test files
            if "__pycache__" in str(file_path):
                continue
            if file_path.name.startswith("_") and file_path.name != "__init__.py":
                continue

            # Focus on test files
            if (
                file_path.name.startswith("test_")
                or file_path.name.endswith("_test.py")
                or file_path.name == "conftest.py"
            ):
                self._analyze_file(file_path, result, use_import_heuristics)

    def _analyze_imports(
        self,
        imports: Set[str],
        result: TestAnalysisResult,
        file_path: str,
    ) -> None:
        """Analyze imports to detect service requirements."""
        imports_str = " ".join(imports)

        for pattern, services in self.import_patterns.items():
            if re.search(pattern, imports_str):
                for service in services:
                    result.add_service(
                        service,
                        f"import pattern '{pattern}' in {file_path}",
                    )

    def _resolve_services(
        self,
        result: TestAnalysisResult,
        blueprint: Optional[Blueprint],
        suite_config: Optional[TestSuiteDefinition],
    ) -> None:
        """Resolve markers to services using available mappings."""

        # Strategy 1: Use blueprint's test_markers on services
        if blueprint:
            for service_name, service_spec in blueprint.services.items():
                for marker in result.discovered_markers:
                    if marker in service_spec.test_markers:
                        result.add_service(
                            service_name,
                            f"marker '{marker}' matches blueprint service",
                        )

        # Strategy 2: Use suite config explicit mappings
        if suite_config:
            # Default services
            for service in suite_config.default_services:
                result.add_service(service, "suite default service")

            # Marker mappings
            for marker in result.discovered_markers:
                services = suite_config.get_services_for_marker(marker)
                for service in services:
                    result.add_service(
                        service,
                        f"marker '{marker}' in suite config",
                    )

            # Fixture mappings
            for fixture in result.discovered_fixtures:
                if fixture in suite_config.fixture_services:
                    for service in suite_config.fixture_services[fixture]:
                        result.add_service(
                            service,
                            f"fixture '{fixture}' in suite config",
                        )

        # Strategy 3: Fall back to default marker mappings
        for marker in result.discovered_markers:
            if marker in self.marker_services:
                default_services = self.marker_services[marker]
                for service in default_services:
                    # Only add if service exists in blueprint (if provided)
                    if blueprint is None or service in blueprint.services:
                        result.add_service(
                            service,
                            f"marker '{marker}' default mapping",
                        )

    def get_minimal_blueprint(
        self,
        blueprint: Blueprint,
        test_paths: List[str],
        suite_config: Optional[TestSuiteDefinition] = None,
        markers: Optional[List[str]] = None,
    ) -> tuple[Blueprint, TestAnalysisResult]:
        """Create a minimal blueprint containing only services needed for tests.

        This is the main entry point for test-aware provisioning. It:
        1. Analyzes test files to discover markers/fixtures
        2. Maps discoveries to required services
        3. Resolves transitive dependencies
        4. Creates a subset blueprint

        Args:
            blueprint: Full blueprint to subset
            test_paths: Test files/directories to analyze
            suite_config: Optional explicit test suite configuration
            markers: Additional markers to include

        Returns:
            Tuple of (minimal Blueprint, analysis result)
        """
        # Analyze tests
        result = self.analyze_tests(
            test_paths=test_paths,
            blueprint=blueprint,
            suite_config=suite_config,
            markers=markers,
        )

        # Create subset blueprint with dependencies
        if result.required_services:
            minimal_blueprint = blueprint.create_subset(result.required_services)
        else:
            # No services detected - return empty or warn
            minimal_blueprint = Blueprint(
                name=f"{blueprint.name}-empty",
                version=blueprint.version,
                services={},
            )

        return minimal_blueprint, result

    def resolve_dependencies(
        self,
        blueprint: Blueprint,
        services: Set[str],
    ) -> List[str]:
        """Resolve services to startup-ordered list including dependencies.

        Args:
            blueprint: Blueprint containing service definitions
            services: Initial set of required services

        Returns:
            List of service names in startup order (dependencies first)
        """
        # Use blueprint's built-in dependency resolution
        all_required = blueprint._resolve_dependencies(services)
        return blueprint.get_startup_order(list(all_required))


def analyze_conftest_fixtures(conftest_path: Path) -> Dict[str, Set[str]]:
    """Analyze a conftest.py file to discover fixture-to-marker mappings.

    This is a helper function to extract fixture definitions and their
    associated pytest markers, which can help build a TestSuiteDefinition.

    Args:
        conftest_path: Path to conftest.py file

    Returns:
        Dict mapping fixture names to sets of markers they use
    """
    fixture_markers: Dict[str, Set[str]] = {}

    try:
        source = conftest_path.read_text()
        tree = ast.parse(source, filename=str(conftest_path))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                is_fixture = False
                markers: Set[str] = set()

                for decorator in node.decorator_list:
                    # Check for @pytest.fixture
                    if isinstance(decorator, ast.Attribute):
                        if decorator.attr == "fixture":
                            is_fixture = True
                    elif isinstance(decorator, ast.Call):
                        if isinstance(decorator.func, ast.Attribute):
                            if decorator.func.attr == "fixture":
                                is_fixture = True
                            elif (
                                hasattr(decorator.func, "value")
                                and hasattr(decorator.func.value, "attr")
                                and decorator.func.value.attr == "mark"
                            ):
                                markers.add(decorator.func.attr)

                if is_fixture:
                    fixture_markers[node.name] = markers

    except Exception:
        pass  # Silently ignore analysis errors for helper function

    return fixture_markers
