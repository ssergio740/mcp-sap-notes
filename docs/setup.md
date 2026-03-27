# Setup Guide

## Prerequisites

- Node.js >= 18.0.0
- npm
- An SAP S-user account with access to SAP Notes

## Installation

```bash
git clone https://github.com/marianfoo/mcp-sap-notes.git
cd mcp-sap-notes
npm install
npm run build
```

### Install Playwright Browsers

```bash
npx playwright install chromium
```

## Configuration

### Option A: Username/Password (Recommended)

Create a `.env` file:

```env
SAP_USERNAME=your.email@company.com
SAP_PASSWORD=your_sap_password
```

Or pass credentials directly in MCP client config (see below).

### Option B: Certificate

1. Download your SAP Passport certificate from [SAP Support Portal](https://launchpad.support.sap.com)
2. Place the `.pfx` file in the `certs/` directory
3. Create a `.env` file:

```env
PFX_PATH=./certs/sap.pfx
PFX_PASSPHRASE=your_certificate_passphrase
```

### Test Authentication

```bash
npm run test:auth
```

For visual debugging:
```bash
npm run test:auth:debug
```

## MCP Client Setup

### Cursor

Add to your Cursor MCP settings (`~/.cursor/mcp.json` or workspace settings):

```json
{
  "mcpServers": {
    "sap-notes": {
      "command": "node",
      "args": ["/absolute/path/to/mcp-sap-notes/dist/mcp-server.js"],
      "env": {
        "SAP_USERNAME": "your.email@company.com",
        "SAP_PASSWORD": "your_sap_password"
      }
    }
  }
}
```

### Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sap-notes": {
      "command": "node",
      "args": ["/absolute/path/to/mcp-sap-notes/dist/mcp-server.js"],
      "env": {
        "SAP_USERNAME": "your.email@company.com",
        "SAP_PASSWORD": "your_sap_password"
      }
    }
  }
}
```

### HTTP Mode (Docker / LibreChat)

Start the HTTP server:
```bash
npm run serve:http
```

Connect via HTTP endpoint:
```
URL: http://localhost:3123/mcp
```

With authentication:
```env
ACCESS_TOKEN=your-secret-token
```

## Available Tools

Once connected, the MCP server exposes two tools:

### `sap_note_search`
Search for SAP Notes by keyword, error code, or note ID.

```
Input: { q: "OData error 415", lang: "EN" }
Output: List of matching SAP Notes with metadata
```

### `sap_note_get`
Fetch the full content of a specific SAP Note.

```
Input: { id: "2744792", lang: "EN" }
Output: Complete note with content, solution steps, etc.
```

## Running Tests

```bash
npm run test:auth    # Test authentication
npm run test:api     # Test SAP API
npm run test:mcp     # Test MCP protocol
npm test             # Run all tests
```

## Development

```bash
npm run dev          # Watch mode (stdio)
npm run dev:http     # Watch mode (HTTP)
```

## Docker

The server can run in Docker with the HTTP transport:

```bash
docker build -t sap-notes-mcp .
docker run -p 3123:3123 \
  -e SAP_USERNAME=your.email@company.com \
  -e SAP_PASSWORD=your_sap_password \
  sap-notes-mcp
```

Ensure the Docker image includes Playwright dependencies (chromium, nss, freetype, harfbuzz).
