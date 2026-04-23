# SAP Note Search MCP Server

Python FastMCP server for SAP Notes and KB articles.

## What it includes

- `search` and `fetch` MCP tools
- SAP authentication with username/password or certificate
- HTTP mode with Azure OAuth and email-domain allowlist
- Playwright browser automation
- Docker image based on the Python runtime

## Install

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e .
python -m playwright install chromium
```

## Run

```bash
mcp-sap-notes-stdio
mcp-sap-notes-http
```

## Configuration

Use [env.example](env.example) for the supported variables.

## Docker

```bash
docker build -t mcp-sap-notes-python .
docker run -it -p 3123:3123 mcp-sap-notes-python
```

## Docs

- [docs/setup.md](docs/setup.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/authentication.md](docs/authentication.md)
