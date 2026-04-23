# Use official Playwright image - includes Chromium and all system deps.
FROM mcr.microsoft.com/playwright:v1.52.0-noble

WORKDIR /app

# Install Python tooling for the FastMCP implementation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Copy Python project metadata and source first for better layer caching.
COPY pyproject.toml README.md ./
COPY py_src/ ./py_src/

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -e .

# Ensure the Playwright browser binary is available for the Python runtime.
RUN /opt/venv/bin/python -m playwright install chromium

# Default environment.
ENV DOCKER_ENV=true \
    NODE_ENV=production \
    HTTP_PORT=8090 \
    HTTP_HOST=0.0.0.0 \
    MCP_HTTP_PATH=/mcp \
    LOG_LEVEL=info \
    MAX_JWT_AGE_H=12 \
    MFA_TIMEOUT=120000 \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1

EXPOSE 3123

# Health check.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import os, sys, urllib.request; port = os.environ.get('HTTP_PORT', '8090'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/mcp', timeout=5).status < 500 else 1)"

CMD ["mcp-sap-notes-http"]
