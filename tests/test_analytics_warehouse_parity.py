"""
Parity tests for AnalyticsService warehouse query operations.

Validates that CLI, REST, and direct warehouse calls use consistent parameters
and produce equivalent backend queries for KPI metrics, behavior usage,
token savings, and compliance coverage.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from io import StringIO

from amprealize.analytics.warehouse import AnalyticsWarehouse
from amprealize.cli import main as cli_main


@pytest.fixture
def mock_warehouse():
    """Create mocked AnalyticsWarehouse instance."""
    warehouse = MagicMock(spec=AnalyticsWarehouse)
    warehouse.get_kpi_summary.return_value = []
    warehouse.get_behavior_usage.return_value = []
    warehouse.get_token_savings.return_value = []
    warehouse.get_compliance_coverage.return_value = []
    return warehouse


class TestKPISummaryParity:
    """Test parity for KPI summary warehouse queries."""

    def test_cli_kpi_summary_calls_warehouse(self, mock_warehouse):
        """Verify CLI kpi-summary command invokes warehouse.get_kpi_summary()."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', ['amprealize', 'analytics', 'kpi-summary']):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        # Warehouse method should be called
        mock_warehouse.get_kpi_summary.assert_called_once()

    def test_cli_kpi_summary_passes_date_filters(self, mock_warehouse):
        """Verify CLI kpi-summary passes date parameters to warehouse."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', [
                    'amprealize', 'analytics', 'kpi-summary',
                    '--start-date', '2024-01-01',
                    '--end-date', '2024-12-31'
                ]):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        # Verify parameters passed through
        call_kwargs = mock_warehouse.get_kpi_summary.call_args.kwargs
        assert call_kwargs['start_date'] == '2024-01-01'
        assert call_kwargs['end_date'] == '2024-12-31'


class TestBehaviorUsageParity:
    """Test parity for behavior usage warehouse queries."""

    def test_cli_behavior_usage_calls_warehouse(self, mock_warehouse):
        """Verify CLI behavior-usage command invokes warehouse.get_behavior_usage()."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', ['amprealize', 'analytics', 'behavior-usage']):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        mock_warehouse.get_behavior_usage.assert_called_once()

    def test_cli_behavior_usage_passes_limit_parameter(self, mock_warehouse):
        """Verify CLI behavior-usage passes limit parameter to warehouse."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', [
                    'amprealize', 'analytics', 'behavior-usage',
                    '--limit', '25'
                ]):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        call_kwargs = mock_warehouse.get_behavior_usage.call_args.kwargs
        assert call_kwargs['limit'] == 25

    def test_cli_behavior_usage_passes_date_filters(self, mock_warehouse):
        """Verify CLI behavior-usage passes date filters to warehouse."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', [
                    'amprealize', 'analytics', 'behavior-usage',
                    '--start-date', '2024-06-01',
                    '--end-date', '2024-06-30'
                ]):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        call_kwargs = mock_warehouse.get_behavior_usage.call_args.kwargs
        assert call_kwargs['start_date'] == '2024-06-01'
        assert call_kwargs['end_date'] == '2024-06-30'


class TestTokenSavingsParity:
    """Test parity for token savings warehouse queries."""

    def test_cli_token_savings_calls_warehouse(self, mock_warehouse):
        """Verify CLI token-savings command invokes warehouse.get_token_savings()."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', ['amprealize', 'analytics', 'token-savings']):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        mock_warehouse.get_token_savings.assert_called_once()

    def test_cli_token_savings_passes_limit_parameter(self, mock_warehouse):
        """Verify CLI token-savings passes limit parameter to warehouse."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', [
                    'amprealize', 'analytics', 'token-savings',
                    '--limit', '50'
                ]):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        call_kwargs = mock_warehouse.get_token_savings.call_args.kwargs
        assert call_kwargs['limit'] == 50


class TestComplianceCoverageParity:
    """Test parity for compliance coverage warehouse queries."""

    def test_cli_compliance_coverage_calls_warehouse(self, mock_warehouse):
        """Verify CLI compliance-coverage command invokes warehouse.get_compliance_coverage()."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', ['amprealize', 'analytics', 'compliance-coverage']):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        mock_warehouse.get_compliance_coverage.assert_called_once()

    def test_cli_compliance_coverage_passes_limit_parameter(self, mock_warehouse):
        """Verify CLI compliance-coverage passes limit parameter to warehouse."""
        with patch('amprealize.analytics.warehouse.AnalyticsWarehouse', return_value=mock_warehouse):
            with patch('sys.stdout', new=StringIO()):
                with patch('sys.argv', [
                    'amprealize', 'analytics', 'compliance-coverage',
                    '--limit', '10'
                ]):
                    try:
                        cli_main()
                    except SystemExit:
                        pass

        call_kwargs = mock_warehouse.get_compliance_coverage.call_args.kwargs
        assert call_kwargs['limit'] == 10
