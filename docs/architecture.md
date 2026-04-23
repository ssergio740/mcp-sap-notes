# Architecture

## System Overview

The SAP Note Search MCP Server is a Python FastMCP server that enables AI assistants to search and retrieve SAP Notes. It bridges the gap between AI tools and SAP's authenticated knowledge base.

## Component Diagram

```
┌─────────────────────────────────────────────────────┐
│                MCP Client Layer                      │
│  (Cursor, Claude Desktop, LibreChat, etc.)           │
└──────────┬──────────────────────┬───────────────────┘
           │ stdio (JSON-RPC)     │ HTTP (Streamable)
           ▼                      ▼
┌──────────────────────┐    ┌──────────────────────────┐
│ server_stdio.py      │    │ server_http.py           │
│ FastMCP stdio        │    │ FastMCP HTTP + OAuth     │
└──────────┬───────────┘    └────────────┬─────────────┘
         │                         │
         └────────┬────────────────┘
                  ▼
       ┌────────────────────┐
       │   MCP Tool Layer    │
       │ search     │
       │ fetch        │
       └─────────┬──────────┘
                 │
    ┌────────────┼────────────┐
    ▼                         ▼
┌──────────┐        ┌─────────────────────┐
│ auth.py  │        │ sap_notes_api.py    │
│ Auth     │        │ Search + Fetch      │
└────┬─────┘        └────────┬────────────┘
     │                       │
     ▼                       ▼
┌─────────────────────────────────────┐
│          External SAP APIs           │
│  accounts.sap.com  (auth)            │
│  me.sap.com        (notes + search)  │
│  Coveo API         (search engine)   │
└─────────────────────────────────────┘
```

## Server Transports

### Stdio Transport (`server_stdio.py`)
- Primary mode for IDE integrations (Cursor, Claude Desktop)
- Communicates via stdin/stdout using FastMCP

### HTTP Transport (`server_http.py`)
- For Docker, LibreChat, and remote deployments
- FastMCP HTTP transport with Microsoft Entra ID / Azure OAuth
- Email-domain allowlist enforced during token validation

## Authentication Layer (`auth.py`)

### Method Resolution
```
1. Check token-cache.json for valid cached cookies
2. Determine auth method:
   - AUTH_METHOD=password → username/password
   - AUTH_METHOD=certificate → client certificate
   - AUTH_METHOD=auto (default):
     - SAP_USERNAME + SAP_PASSWORD set → password
     - PFX_PATH + PFX_PASSPHRASE set → certificate
3. Launch Playwright browser
4. Perform selected auth flow
5. Extract session cookies
6. Cache cookies to token-cache.json
```

### Username/Password Flow
1. Navigate to `me.sap.com/home`
2. Detect login form on `accounts.sap.com`
3. Fill username field (multiple selector strategies)
4. Handle single-page or multi-step login forms
5. Fill password field
6. Submit form
7. Wait for MFA/2FA if detected (configurable timeout)
8. Extract session cookies after redirect

### Certificate Flow
1. Create browser context with PFX client certificate
2. Navigate to `me.sap.com/home`
3. Certificate presented during TLS handshake
4. Wait for auth redirect with 2FA support
5. Extract session cookies

### Token Caching
- Cookies serialized as semicolon-separated string
- Stored in `token-cache.json` with expiry timestamp
- 5-minute buffer before expiry to prevent edge cases
- Single-flight guard prevents concurrent auth attempts

## API Layer (`sap_notes_api.py`)

### Search Strategy (Multi-tier Fallback)

```
Search Request
    │
    ├─ Tier 1: Coveo Search API (primary)
    │  ├─ Extract Coveo bearer token from SAP session
    │  ├─ POST to Coveo with query + document type filter
    │  └─ Return ranked results
    │
    ├─ Tier 2: Direct Note ID Lookup (if query is numeric)
    │  ├─ Detect note ID pattern (6-8 digits)
    │  └─ Call getNote() directly
    │
    └─ Tier 3: SAP Internal Search API
       └─ Bypass Coveo, query SAP directly
```

### Note Retrieval Strategy

```
Get Note Request
    │
    ├─ Method 1: Playwright Raw Notes API
    │  ├─ Launch browser with auth cookies
    │  ├─ Navigate to me.sap.com/backend/raw/sapnotes/Detail
    │  └─ Extract JSON from page
    │
    └─ Method 2: HTTP Raw Notes API (fallback)
       ├─ Direct fetch with browser-like headers
       └─ Parse JSON/HTML response
```

## Schema Layer

The Python handlers validate the important inputs directly and keep the responses shaped for MCP clients.

## Logging

- Python logging with configurable levels via `LOG_LEVEL`
- Sensitive fields are kept out of the main response path

## HTTP Authorization (`azure_auth.py`)

- Serves OAuth protected-resource metadata for the MCP endpoint
- Validates Azure access tokens via OIDC discovery and JWKS verification
- Enforces audience, issuer, required scopes, and allowed email domains
- Returns `WWW-Authenticate` challenges for 401/403 responses

## Data Flow

```
User asks about SAP error
    │
    ▼
MCP Client sends tool call
    │
    ▼
FastMCP handler receives the request
    │
    ▼
Tool handler calls `ensure_authenticated()`
    │
    ├─ Cache hit → return token
    └─ Cache miss → browser auth → cache → return token
    │
    ▼
API client executes search/get with token
    │
    ▼
Results formatted as MCP response
    │
    ▼
Client receives structured results
```
