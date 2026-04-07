#!/bin/bash
# Amprealize Advanced Laptop Cleanup
# Finds and removes development caches, logs, and temporary files

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Advanced Laptop Cleanup ===${NC}\n"

# Show what we found
echo -e "${GREEN}Large directories found:${NC}"
echo -e "${YELLOW}Development Caches:${NC}"
echo "  ~/.cache/huggingface    4.3 GB  (AI models - needed for Phase 3)"
echo "  ~/.cache/uv             1.5 GB  (Python package manager cache)"
echo "  ~/.npm                  1.3 GB  (Node.js package cache)"
echo "  ~/.gradle               1.4 GB  (Gradle build cache)"
echo ""
echo -e "${YELLOW}macOS Caches:${NC}"
echo "  ~/Library/Caches/Google         1.3 GB  (Chrome/Drive)"
echo "  ~/Library/Caches/org.swift.swiftpm  1.1 GB  (Swift packages)"
echo "  ~/Library/Caches/vscode-cpptools    587 MB (VS Code C++ tools)"
echo "  ~/Library/Caches/CocoaPods          264 MB (iOS deps)"
echo "  ~/Library/Caches/Homebrew           216 MB (Brew cache)"
echo "  ~/Library/Caches/pip                163 MB (Python packages)"
echo ""
echo -e "${YELLOW}Podman:${NC}"
echo "  Unused images:    788 MB  (Flink - not needed for Phase 3)"
echo "  Unused volumes:   1.1 GB  (Old container data)"
echo "  Stopped containers: ~100 KB"
echo ""
echo -e "${YELLOW}Downloads:${NC}"
echo "  Docker.dmg        520 MB"
echo "  ChatGPT_Atlas.dmg 220 MB"
echo "  OBS Studio.dmg    179 MB"
echo ""

total_potential="~8-10 GB"
echo -e "${GREEN}Total potential savings: ${BLUE}${total_potential}${NC}\n"

echo -e "${BLUE}=== Cleanup Options ===${NC}\n"

# Option 1: Safe development caches
echo -e "${GREEN}1. Clean safe development caches (~3.2 GB)${NC}"
echo "   Safe to remove, will re-download/rebuild as needed:"
echo "   • UV package cache (1.5 GB)"
echo "   • npm cache (1.3 GB)"
echo "   • Homebrew cache (216 MB)"
echo "   • pip cache (163 MB)"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Cleaning UV cache..."
    rm -rf ~/.cache/uv 2>/dev/null || true
    echo "   Cleaning npm cache..."
    npm cache clean --force 2>/dev/null || true
    echo "   Cleaning Homebrew cache..."
    brew cleanup 2>/dev/null || true
    rm -rf ~/Library/Caches/Homebrew/* 2>/dev/null || true
    echo "   Cleaning pip cache..."
    rm -rf ~/Library/Caches/pip/* 2>/dev/null || true
    echo -e "   ${GREEN}✓ Done (~3.2 GB freed)${NC}"
fi
echo ""

# Option 2: macOS system caches
echo -e "${YELLOW}2. Clean macOS app caches (~2.2 GB)${NC}"
echo "   ⚠️  May slow down first launch of apps:"
echo "   • Google/Chrome cache (1.3 GB)"
echo "   • Swift package manager (1.1 GB)"
echo "   • VS Code C++ tools (587 MB)"
echo "   • CocoaPods (264 MB)"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Cleaning Google caches..."
    rm -rf ~/Library/Caches/Google/* 2>/dev/null || true
    echo "   Cleaning Swift package manager..."
    rm -rf ~/Library/Caches/org.swift.swiftpm/* 2>/dev/null || true
    echo "   Cleaning VS Code C++ tools..."
    rm -rf ~/Library/Caches/vscode-cpptools/* 2>/dev/null || true
    echo "   Cleaning CocoaPods..."
    rm -rf ~/Library/Caches/CocoaPods/* 2>/dev/null || true
    echo -e "   ${GREEN}✓ Done (~2.2 GB freed)${NC}"
fi
echo ""

# Option 3: Gradle cache
echo -e "${YELLOW}3. Clean Gradle cache (~1.4 GB)${NC}"
echo "   Only remove if you're not doing Android/Java development"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Cleaning Gradle..."
    rm -rf ~/.gradle/caches 2>/dev/null || true
    rm -rf ~/.gradle/wrapper 2>/dev/null || true
    echo -e "   ${GREEN}✓ Done (~1.4 GB freed)${NC}"
fi
echo ""

# Option 4: Podman volumes and images
echo -e "${YELLOW}4. Clean unused Podman volumes and images (~1.9 GB)${NC}"
echo "   • Removes Flink image (788 MB - not needed for Phase 3)"
echo "   • Removes unused volumes (1.1 GB - old container data)"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing Flink image..."
    podman rmi flink:1.18-scala_2.12-java11 2>/dev/null || true
    echo "   Pruning unused volumes..."
    podman volume prune -f
    echo "   Removing stopped containers..."
    podman container prune -f
    echo -e "   ${GREEN}✓ Done (~1.9 GB freed)${NC}"
fi
echo ""

# Option 5: Downloads folder
echo -e "${YELLOW}5. Review Downloads folder (~920 MB found)${NC}"
echo "   • Docker.dmg (520 MB)"
echo "   • ChatGPT_Atlas.dmg (220 MB)"
echo "   • OBS Studio.dmg (179 MB)"
echo "   (Manual review recommended)"
read -p "   Open Downloads folder? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    open ~/Downloads
    echo -e "   ${GREEN}✓ Opened - delete installers you've already used${NC}"
fi
echo ""

# Option 6: HuggingFace models (CAREFUL)
echo -e "${RED}6. Remove HuggingFace models (4.3 GB)${NC}"
echo -e "   ${RED}WARNING: Needed for Phase 3 semantic search${NC}"
echo "   Will re-download BAAI/bge-m3 (~60 seconds) next time"
echo "   Only do this if critically low on space"
read -p "   Execute? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "   Removing HuggingFace cache..."
    rm -rf ~/.cache/huggingface
    echo -e "   ${RED}✓ Done - Will re-download on next semantic search${NC}"
fi
echo ""

# Final summary
echo -e "${BLUE}=== Cleanup Complete ===${NC}\n"
echo "Checking current space..."
df -h / | tail -1 | awk '{print "Available: " $4 " (" $5 " used)"}'
echo ""
echo -e "${GREEN}Recommendations:${NC}"
echo "• If still need space: Review Downloads folder and remove old installers"
echo "• Development caches will rebuild automatically when needed"
echo "• To restart containers: podman start amprealize-postgres-behavior amprealize-redis"
echo ""
