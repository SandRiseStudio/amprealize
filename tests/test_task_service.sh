#!/bin/bash
# Simple wrapper to test TaskService via MCP with proper environment

# Source PostgreSQL credentials
source .env.postgres

# Set default database URL for other services (AgentAuthService, etc.)
export DATABASE_URL="postgresql://amprealize_telemetry:dev_telemetry_pass@localhost:5432/telemetry"

# Run integration test
echo "Running TaskService integration test..."
python test_task_integration.py
