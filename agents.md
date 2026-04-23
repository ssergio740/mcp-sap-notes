# SAP Note Search MCP Server - Project Overview for Claude Sessions

## What This Project Is

A Python FastMCP server that gives AI assistants direct access to SAP Notes and Knowledge Base articles. It authenticates with SAP's systems via browser automation (Playwright) and exposes two tools: **search** and **fetch** for SAP Notes.

## Architecture Overview

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e .

# Stdio mode (for Cursor)
mcp-sap-notes-stdio

# HTTP mode (for Docker/LibreChat)
mcp-sap-notes-http
```
                       ▼
         ┌──────────────────────────┐
         │  MCP Tool Handlers       │
         │  search         │
         │  fetch            │
         └────────────┬─────────────┘
                      │
        ┌─────────────┴──────────────┐
        ▼                            ▼
┌──────────────────┐    ┌────────────────────────┐
│  py_src/.../auth.py │  py_src/.../sap_notes_api.py      │
│  SapAuthenticator   │  SapNotesApiClient                │
│  Playwright +       │  Coveo Search API                 │
│  Certificate/Password │ Raw Notes API                  │
└──────────────────┘    └────────────────────────┘
        │                            │
        ▼                            ▼
┌──────────────────────────────────────────────┐
│  SAP Systems                                  │
│  • accounts.sap.com (IAS - authentication)    │
│  • me.sap.com (notes, search, Coveo token)    │
│  • Coveo search engine (search API)           │
│  • launchpad.support.sap.com (note URLs)      │
└──────────────────────────────────────────────┘
```

## Source Files

### Core Server Files

| File | Purpose | Key Classes/Exports |
|------|---------|-------------------|
| `py_src/mcp_sap_notes/server_stdio.py` | Main stdio entry point | `main()` |
| `py_src/mcp_sap_notes/server_http.py` | HTTP entry point | `main()` |
| `py_src/mcp_sap_notes/auth.py` | Authentication via Playwright browser automation | `SapAuthenticator` |
| `py_src/mcp_sap_notes/sap_notes_api.py` | SAP Notes search and retrieval | `SapNotesApiClient` |
| `py_src/mcp_sap_notes/config.py` | Configuration loading | `ServerConfig`, `load_config()` |
| `py_src/mcp_sap_notes/azure_auth.py` | Azure OAuth with domain allowlist | `DomainFilteredAzureProvider` |
| `py_src/mcp_sap_notes/html_utils.py` | HTML-to-text parsing | `strip_html`, `parse_note_content` |

### Test Files

| File | Purpose |
|------|---------|
| Python smoke tests | Run from the container or ad hoc Python snippets |

### Configuration

| File | Purpose |
|------|---------|
| `.env` / `.env.example` | Environment variables (SAP_USERNAME, PFX_PATH, Azure OAuth, etc.) |
| `pyproject.toml` | Python packaging and scripts |
| `token-cache.json` | Cached authentication cookies (auto-generated) |

## Authentication Flow

The server supports two authentication methods:

### 1. Certificate-Based (Original)
- Uses a `.pfx` client certificate for SAP IAS
- Playwright launches a browser, presents the certificate during TLS handshake
- SAP authenticates automatically, browser extracts session cookies
- Cookies cached to `token-cache.json` with configurable TTL

### 2. Username/Password (New)
- Uses SAP username + password for form-based login
- Playwright fills the login form on `accounts.sap.com`
- Supports MFA/2FA with configurable timeout for manual code entry
- Credentials passed via env vars (`SAP_USERNAME`, `SAP_PASSWORD`) or MCP client config
- Falls back to certificate auth if username/password not provided

### Auth Priority
1. Check `token-cache.json` for valid cached token
2. If `SAP_USERNAME` + `SAP_PASSWORD` provided → username/password auth
3. If `PFX_PATH` + `PFX_PASSPHRASE` provided → certificate auth
4. Error if neither configured

## MCP Tools

### `search`
- **Input:** `{ q: string, lang?: 'EN' | 'DE' }`
- **Flow:** Coveo search API → fallback to direct ID lookup → fallback to SAP internal search
- **Output:** Ranked list of matching SAP Notes with metadata

### `fetch`
- **Input:** `{ id: string, lang?: 'EN' | 'DE' }`
- **Flow:** Playwright raw notes API → fallback to HTTP raw notes API
- **Output:** Full note content (HTML), metadata, priority, category

## Key External APIs

| API | URL | Auth | Purpose |
|-----|-----|------|---------|
| Coveo Search | `sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2` | Bearer token | Search SAP Notes |
| SAP Raw Notes | `me.sap.com/backend/raw/sapnotes/Detail` | Cookies | Fetch note content |
| SAP Search Page | `me.sap.com/search` | Cookies | Extract Coveo token from page |
| SAP IAS | `accounts.sap.com` | Certificate or form login | Authentication |

## Dependencies

| Package | Purpose |
|---------|---------|
| `@modelcontextprotocol/sdk` | Official MCP SDK (server, transports) |
| `playwright` | Browser automation for auth + note retrieval |
| `express` + `cors` | HTTP server mode |
| `zod` | Schema validation for MCP tools |
| `pino` + `pino-pretty` | Structured logging |
| `dotenv` | Environment variable loading |

## Running the Server

```bash
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e .

# Stdio mode (for Cursor)
mcp-sap-notes-stdio

# HTTP mode (for Docker/LibreChat)
mcp-sap-notes-http
```

## MCP Client Configuration

### Cursor / Claude Desktop (stdio)
```json
{
  "mcpServers": {
    "sap-notes": {
      "command": "mcp-sap-notes-stdio",
      "env": {
        "SAP_USERNAME": "your-sap-user",
        "SAP_PASSWORD": "your-sap-password"
      }
    }
  }
}
```

### HTTP Mode
      "command": "mcp-sap-notes-stdio",
  "mcpServers": {
    "sap-notes": {
      "url": "http://localhost:3123/mcp",
      "headers": {
        "Authorization": "Bearer your-access-token"
      }
    }
  }
}
```

## Common Development Tasks

### Adding a new tool
1. Implement the handler in `py_src/mcp_sap_notes/server_core.py`
2. Add or adjust validation in `py_src/mcp_sap_notes/config.py`
3. Implement the API call in `py_src/mcp_sap_notes/sap_notes_api.py`
4. Wire HTTP auth in `py_src/mcp_sap_notes/server_http.py` if needed

### Modifying authentication
- Auth logic is in `py_src/mcp_sap_notes/auth.py`
- Config loaded in `py_src/mcp_sap_notes/config.py`
- Token cache: `token-cache.json` at project root

### Updating tool descriptions
- Tool descriptions live in `py_src/mcp_sap_notes/server_core.py`
- Keep them concise and task-focused

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PFX_PATH` | For cert auth | - | Path to .pfx certificate |
| `PFX_PASSPHRASE` | For cert auth | - | Certificate passphrase |
| `SAP_USERNAME` | For user auth | - | SAP username (email) |
| `SAP_PASSWORD` | For user auth | - | SAP password |
| `MAX_JWT_AGE_H` | No | `12` | Token cache lifetime (hours) |
| `HEADFUL` | No | `false` | Show browser window |
| `LOG_LEVEL` | No | `info` | debug/info/warn/error |
| `HTTP_PORT` | No | `3123` | HTTP server port |
| `MCP_SERVER_URL` | Yes (HTTP) | - | Public MCP resource URL |
| `AZURE_TENANT_ID` | Yes (HTTP) | - | Microsoft Entra tenant ID |
| `AZURE_CLIENT_ID` | Yes (HTTP) | - | Microsoft Entra application client ID |
| `AZURE_CLIENT_SECRET` | Yes (HTTP) | - | Microsoft Entra application client secret |
| `AZURE_REQUIRED_SCOPES` | No | `access_as_user` | Required scope list |
| `ALLOWED_EMAIL_DOMAINS` | Yes (HTTP) | - | Allowed email domains |
