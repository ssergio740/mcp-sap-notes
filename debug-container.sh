#!/bin/bash
# Docker Container Debugging Script for SAP Notes MCP Server
# This script helps debug Playwright and Chromium issues in Docker containers

echo "🐳 SAP Notes MCP Server - Docker Debug Script"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to run commands with error handling
run_cmd() {
    local cmd="$1"
    local description="$2"
    
    echo -e "${BLUE}[DEBUG]${NC} $description"
    echo "Running: $cmd"
    
    if eval "$cmd"; then
        echo -e "${GREEN}✅ Success${NC}"
    else
        echo -e "${RED}❌ Failed${NC}"
    fi
    echo ""
}

# Check if we're in a Docker container
if [ -f /.dockerenv ] || grep -q 'docker' /proc/self/cgroup 2>/dev/null; then
    echo -e "${GREEN}✅ Running inside Docker container${NC}"
else
    echo -e "${YELLOW}⚠️  Not running in Docker container${NC}"
fi
echo ""

# 1. System Information
echo -e "${BLUE}🔍 SYSTEM INFORMATION${NC}"
echo "Platform: $(uname -a)"
echo "Memory: $(free -h | grep Mem: | awk '{print $2 " total, " $7 " available"}')"
echo "Disk space: $(df -h / | tail -1 | awk '{print $2 " total, " $4 " available"}')"
echo ""

# 2. Package Manager and Browser Installation
echo -e "${BLUE}📦 CHECKING BROWSERS${NC}"

# Check for browsers
browsers=("/usr/bin/chromium" "/usr/bin/chromium-browser" "/usr/bin/google-chrome" "/usr/bin/firefox")
found_browser=false

for browser in "${browsers[@]}"; do
    if [ -f "$browser" ]; then
        echo -e "${GREEN}✅ Found: $browser${NC}"
        echo "   Version: $($browser --version 2>/dev/null || echo 'Unknown')"
        found_browser=true
    else
        echo -e "${RED}❌ Not found: $browser${NC}"
    fi
done

if [ "$found_browser" = false ]; then
    echo -e "${YELLOW}⚠️  No system browsers found${NC}"
    
    # Try to install chromium if we have apk (Alpine)
    if command -v apk >/dev/null 2>&1; then
        echo "Installing Chromium via APK..."
        run_cmd "apk update && apk add --no-cache chromium nss freetype harfbuzz ca-certificates fonts-noto" "Installing browser dependencies"
    elif command -v apt-get >/dev/null 2>&1; then
        echo "Installing Chromium via APT..."
        run_cmd "apt-get update && apt-get install -y chromium-browser" "Installing Chromium"
    fi
fi
echo ""

# 3. Playwright Environment
echo -e "${BLUE}🎭 PLAYWRIGHT ENVIRONMENT${NC}"
echo "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD: ${PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD:-NOT_SET}"
echo "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH: ${PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH:-NOT_SET}"
echo "PLAYWRIGHT_BROWSERS_PATH: ${PLAYWRIGHT_BROWSERS_PATH:-NOT_SET}"

# Check Playwright cache
CACHE_DIR="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
echo "Cache directory: $CACHE_DIR"

if [ -d "$CACHE_DIR" ]; then
    echo -e "${GREEN}✅ Cache directory exists${NC}"
    echo "Contents:"
    ls -la "$CACHE_DIR" | head -10
    
    if [ $(ls -1 "$CACHE_DIR" | wc -l) -eq 0 ]; then
        echo -e "${YELLOW}⚠️  Cache directory is empty${NC}"
    fi
else
    echo -e "${RED}❌ Cache directory does not exist${NC}"
fi
echo ""

# 4. Install Playwright browsers if needed
echo -e "${BLUE}📥 PLAYWRIGHT BROWSERS${NC}"
if [ ! -d "$CACHE_DIR" ] || [ $(ls -1 "$CACHE_DIR" 2>/dev/null | wc -l) -eq 0 ]; then
    echo "Installing Playwright browsers..."
    cd /app || exit 1
    run_cmd "python3 -m pip install --quiet --disable-pip-version-check -e ." "Installing Python FastMCP package"
    run_cmd "python3 -m playwright install chromium" "Installing Playwright Chromium"
else
    echo -e "${GREEN}✅ Playwright browsers appear to be installed${NC}"
fi
echo ""

# 5. Run comprehensive debug test
echo -e "${BLUE}🧪 RUNNING COMPREHENSIVE DEBUG TEST${NC}"
cd /app || exit 1

if [ -f "py_src/mcp_sap_notes/server_http.py" ]; then
    run_cmd "python3 -c \"import mcp_sap_notes.server_http; print('Python HTTP entrypoint import OK')\"" "Running Python HTTP smoke test"
else
    echo -e "${RED}❌ Python entrypoint not found${NC}"
fi
echo ""

# 6. Run authentication test with debug
echo -e "${BLUE}🔐 RUNNING AUTHENTICATION TEST${NC}"

# Check for certificate and environment
if [ -n "$PFX_PATH" ] && [ -f "$PFX_PATH" ]; then
    echo -e "${GREEN}✅ Certificate found: $PFX_PATH${NC}"
    echo "   File size: $(du -h "$PFX_PATH" | cut -f1)"
    echo "   Permissions: $(ls -l "$PFX_PATH" | cut -d' ' -f1)"
    
    # Set debugging environment
    export HEADFUL=false
    export LOG_LEVEL=debug
    
    echo "Running authentication smoke test with enhanced debugging..."
    run_cmd "python3 -c \"import mcp_sap_notes.auth; print('Python auth module import OK')\"" "SAP authentication smoke test"
    
else
    echo -e "${YELLOW}⚠️  Certificate not configured or not found${NC}"
    echo "PFX_PATH: ${PFX_PATH:-NOT_SET}"
    if [ -n "$PFX_PATH" ]; then
        echo "File exists: $([ -f "$PFX_PATH" ] && echo 'YES' || echo 'NO')"
    fi
fi
echo ""

# 7. Manual browser test
echo -e "${BLUE}🌐 MANUAL BROWSER TEST${NC}"
if [ -f "/usr/bin/chromium" ]; then
    echo "Testing manual browser launch..."
    timeout 10s chromium --headless --disable-gpu --no-sandbox --dump-dom --virtual-time-budget=1000 data:text/html,"<h1>Test</h1>" 2>&1 | head -5
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Manual browser test successful${NC}"
    else
        echo -e "${RED}❌ Manual browser test failed${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  No chromium executable found for manual test${NC}"
fi
echo ""

# 8. Summary and recommendations
echo -e "${BLUE}📋 SUMMARY AND RECOMMENDATIONS${NC}"

if [ "$found_browser" = true ]; then
    echo -e "${GREEN}✅ System browser available${NC}"
else
    echo -e "${RED}❌ No system browser found - install chromium${NC}"
fi

if [ -d "$CACHE_DIR" ] && [ $(ls -1 "$CACHE_DIR" 2>/dev/null | wc -l) -gt 0 ]; then
    echo -e "${GREEN}✅ Playwright browsers installed${NC}"
else
    echo -e "${RED}❌ Playwright browsers missing - run 'npx playwright install'${NC}"
fi

if [ -n "$PFX_PATH" ] && [ -f "$PFX_PATH" ]; then
    echo -e "${GREEN}✅ Certificate configured${NC}"
else
    echo -e "${YELLOW}⚠️  Certificate not configured${NC}"
fi

echo ""
echo -e "${BLUE}🎯 Next steps:${NC}"
echo "1. Fix any issues identified above"
echo "2. Run: mcp-sap-notes-http"
echo "3. If successful, the MCP server should work"
echo "4. Check server logs: docker logs <container_name>"
echo ""

echo -e "${GREEN}Debug script completed!${NC}"
