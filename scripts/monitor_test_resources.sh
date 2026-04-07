#!/usr/bin/env bash
# Monitor Podman container resources during test execution
# Behaviors: behavior_instrument_metrics_pipeline, behavior_align_storage_layers

set -euo pipefail

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Thresholds
CPU_WARN_THRESHOLD=80
MEM_WARN_THRESHOLD=85
CPU_CRITICAL_THRESHOLD=95
MEM_CRITICAL_THRESHOLD=95

echo "==================================================================="
echo "Podman Container Resource Monitor"
echo "==================================================================="
echo ""

# Check if podman is available
if ! command -v podman &> /dev/null; then
    echo -e "${RED}ERROR: podman command not found${NC}"
    exit 1
fi

# Get container stats
echo "Current container resource usage:"
echo ""

# Use table format - more reliable than JSON with Podman
if podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}" 2>/dev/null | tail -n +2 | while IFS=$'\t' read -r name cpu mem mem_perc; do
    # Skip empty lines
    [ -z "$name" ] && continue

    # Remove % signs for comparison
    cpu_val="${cpu%\%}"
    mem_val="${mem_perc%\%}"

    # Determine status color (handle non-numeric values)
    status="${GREEN}OK${NC}"
    if [[ "$cpu_val" =~ ^[0-9]+\.?[0-9]*$ ]] && [[ "$mem_val" =~ ^[0-9]+\.?[0-9]*$ ]]; then
        if (( $(echo "$cpu_val > $CPU_WARN_THRESHOLD" | bc -l 2>/dev/null || echo 0) )) || \
           (( $(echo "$mem_val > $MEM_WARN_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
            status="${YELLOW}WARN${NC}"
        fi
        if (( $(echo "$cpu_val > $CPU_CRITICAL_THRESHOLD" | bc -l 2>/dev/null || echo 0) )) || \
           (( $(echo "$mem_val > $MEM_CRITICAL_THRESHOLD" | bc -l 2>/dev/null || echo 0) )); then
            status="${RED}CRITICAL${NC}"
        fi
    fi

    printf "%-40s CPU: %6s  Memory: %20s (%5s)  [%b]\n" \
        "$name" "$cpu" "$mem" "$mem_perc" "$status"
done; then
    : # Success - stats displayed above
else
    echo -e "${YELLOW}Note: Unable to retrieve container stats${NC}"
fi

echo ""
echo "==================================================================="
echo "Active test database containers:"
podman ps --filter "name=amprealize" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "==================================================================="
echo "System resources:"
echo ""

# macOS specific memory info
if [[ "$OSTYPE" == "darwin"* ]]; then
    # Get memory pressure
    memory_pressure=$(memory_pressure 2>&1 | head -1 || echo "Unknown")
    echo "Memory pressure: $memory_pressure"

    # Get top processes by memory
    echo ""
    echo "Top 5 memory consumers:"
    ps aux | sort -nrk 4 | head -6 | awk 'NR==1 || NR>1' | \
        awk '{printf "  %-20s %6s%% %10s\n", substr($11,1,20), $4, $6}'
else
    # Linux memory info
    free -h
fi

echo ""
echo "==================================================================="
echo "Recommendations:"
echo ""

# Check if any containers are using excessive resources
high_usage=false
while IFS=$'\t' read -r name cpu mem mem_perc; do
    [ -z "$name" ] && continue

    # Remove % signs
    cpu_val="${cpu%\%}"
    mem_val="${mem_perc%\%}"

    # Check if values are numeric and exceed thresholds
    if [[ "$cpu_val" =~ ^[0-9]+\.?[0-9]*$ ]] && [[ "$mem_val" =~ ^[0-9]+\.?[0-9]*$ ]]; then
        if (( $(echo "$cpu_val > 80" | bc -l 2>/dev/null || echo 0) )) || \
           (( $(echo "$mem_val > 80" | bc -l 2>/dev/null || echo 0) )); then
            high_usage=true
            echo -e "${YELLOW}⚠${NC}  Container '$name' is under heavy load (CPU: $cpu, Memory: $mem_perc)"
        fi
    fi
done < <(podman stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}" 2>/dev/null | tail -n +2)

if [ "$high_usage" = true ]; then
    echo ""
    echo "Suggestions to reduce resource usage:"
    echo "  • Run tests serially: pytest tests/ (no -n flag)"
    echo "  • Run smaller test suites: pytest tests/test_cli_*.py"
    echo "  • Increase container resource limits in docker-compose.test.yml"
    echo "  • Restart containers: podman-compose -f docker-compose.test.yml restart"
else
    echo -e "${GREEN}✓${NC} All containers are operating within normal parameters"
    echo ""
    echo "Safe to run tests with limited parallelization:"
    echo "  • Serial: pytest tests/"
    echo "  • Parallel (2 workers): pytest -n 2 --dist=loadfile tests/"
fi

echo ""
echo "==================================================================="
