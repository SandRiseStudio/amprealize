#!/bin/bash
# Amprealize Resource Cleanup Script
# Helps free up disk space and resources on your laptop

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Amprealize Resource Cleanup ===${NC}\n"

# Function to show size
show_size() {
    local path=$1
    local desc=$2
    if [ -e "$path" ]; then
        local size=$(du -sh "$path" 2>/dev/null | cut -f1)
        echo -e "${YELLOW}$desc:${NC} $size"
    fi
}

# Show current usage
echo -e "${GREEN}Current Resource Usage:${NC}"
show_size "/Users/nick/.cache/huggingface" "HuggingFace models"
show_size "/Users/nick/amprealize/.venv" "Python venv"
show_size "/Users/nick/amprealize/data" "Project data"
show_size "/Users/nick/amprealize/extension/node_modules" "Extension node_modules"
echo ""

# Count Python cache
pycache_count=$(find /Users/nick/amprealize -name "*.pyc" -o -name "__pycache__" -type d 2>/dev/null | wc -l | tr -d ' ')
echo -e "${YELLOW}Python cache files/dirs:${NC} $pycache_count"
echo ""

# Show containers
echo -e "${GREEN}Podman Containers:${NC}"
podman ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Size}}"
echo ""

# Show images
echo -e "${GREEN}Podman Images:${NC}"
podman images --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
echo ""

echo -e "${BLUE}=== Cleanup Options ===${NC}\n"

# Option 1: Remove stopped containers
echo -e "${YELLOW}1. Remove stopped containers (keeps running ones)${NC}"
echo "   Frees: ~few MB, reduces clutter"
echo "   Safe: Yes, can recreate with docker-compose"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing stopped containers..."
    podman container prune -f
    echo -e "   ${GREEN}✓ Done${NC}"
fi
echo ""

# Option 2: Clean Python cache
echo -e "${YELLOW}2. Remove Python cache files (__pycache__, *.pyc)${NC}"
echo "   Frees: ~few MB"
echo "   Safe: Yes, regenerated automatically"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing Python cache..."
    find /Users/nick/amprealize -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find /Users/nick/amprealize -name "*.pyc" -delete 2>/dev/null || true
    echo -e "   ${GREEN}✓ Done${NC}"
fi
echo ""

# Option 3: Remove unused Podman images
echo -e "${YELLOW}3. Remove unused/dangling Podman images${NC}"
echo "   Frees: Could be 1-2 GB"
echo "   Safe: Yes for dangling images, but may need to re-pull"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing dangling images..."
    podman image prune -f
    echo -e "   ${GREEN}✓ Done${NC}"
fi
echo ""

# Option 4: Remove HuggingFace cache (CAREFUL)
echo -e "${RED}4. Remove HuggingFace model cache (4.3 GB)${NC}"
echo -e "   Frees: ${RED}~4.3 GB${NC}"
echo -e "   ${RED}WARNING: Will re-download BAAI/bge-m3 (2.27GB) next run (~60s download)${NC}"
echo "   Use only if you need immediate space"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing HuggingFace cache..."
    rm -rf /Users/nick/.cache/huggingface
    echo -e "   ${GREEN}✓ Done - Model will re-download on next semantic search${NC}"
fi
echo ""

# Option 5: Stop all containers
echo -e "${YELLOW}5. Stop all running containers (keep data, just stop)${NC}"
echo "   Frees: RAM and CPU, no disk space"
echo "   Safe: Yes, restart with 'podman start <name>'"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Stopping all containers..."
    podman stop $(podman ps -q) 2>/dev/null || echo "   No running containers"
    echo -e "   ${GREEN}✓ Done${NC}"
fi
echo ""

# Option 6: Remove analytics infrastructure (advanced)
echo -e "${YELLOW}6. Remove analytics/telemetry containers (Metabase, Kafka, etc.)${NC}"
echo "   Frees: ~2-3 GB images + container data"
echo "   Impact: Disables analytics dashboards until recreated"
echo "   Can recreate: docker-compose -f docker-compose.analytics-dashboard.yml up"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Stopping and removing analytics containers..."
    podman stop amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true
    podman rm amprealize-metabase amprealize-kafka amprealize-zookeeper amprealize-kafka-ui 2>/dev/null || true
    echo "   Removing analytics images..."
    podman rmi metabase/metabase:v0.48.0 2>/dev/null || true
    podman rmi confluentinc/cp-kafka:7.5.0 2>/dev/null || true
    podman rmi confluentinc/cp-zookeeper:7.5.0 2>/dev/null || true
    podman rmi provectuslabs/kafka-ui:latest 2>/dev/null || true
    podman rmi dpage/pgadmin4:latest 2>/dev/null || true
    echo -e "   ${GREEN}✓ Done - Analytics infrastructure removed${NC}"
fi
echo ""

# Show final usage
echo -e "${BLUE}=== Final Resource Usage ===${NC}\n"
show_size "/Users/nick/.cache/huggingface" "HuggingFace models"
show_size "/Users/nick/amprealize/.venv" "Python venv"
show_size "/Users/nick/amprealize/data" "Project data"
echo ""
echo -e "${GREEN}Cleanup complete!${NC}"
echo ""
echo -e "${BLUE}To restart containers later:${NC}"
echo "  podman start amprealize-postgres-behavior    # For Phase 3 work"
echo "  podman start amprealize-redis                # For caching"
echo ""
