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

The Dockerfile is based on the official Playwright image and includes Chromium pre-installed.

### Build

```bash
docker build -t mcp-sap-notes .
```

### Run with username/password

```bash
docker run -d --name mcp-sap-notes \
  --shm-size=1g \
  -p 3123:3123 \
  -e SAP_USERNAME=your.email@company.com \
  -e SAP_PASSWORD=your_sap_password \
  mcp-sap-notes
```

### Run with certificate

```bash
docker run -d --name mcp-sap-notes \
  --shm-size=1g \
  -p 3123:3123 \
  -v ./certs:/app/certs:ro \
  -e PFX_PATH=/app/certs/sap.pfx \
  -e PFX_PASSPHRASE=your_passphrase \
  mcp-sap-notes
```

### With endpoint authentication

```bash
docker run -d --name mcp-sap-notes \
  --shm-size=1g \
  -p 3123:3123 \
  -e SAP_USERNAME=your.email@company.com \
  -e SAP_PASSWORD=your_sap_password \
  -e ACCESS_TOKEN=your-secret-token \
  mcp-sap-notes
```

### Docker Compose (LibreChat)

```yaml
services:
  sap_notes:
    image: mcp-sap-notes:latest
    container_name: mcp-sap-notes
    ports:
      - "3123:3123"
    shm_size: 1g
    environment:
      - SAP_USERNAME=${SAP_USERNAME}
      - SAP_PASSWORD=${SAP_PASSWORD}
      - ACCESS_TOKEN=${ACCESS_TOKEN}
      - LOG_LEVEL=info
```

### Verify

```bash
# Health check
curl http://localhost:3123/health

# Test search
curl -X POST http://localhost:3123/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

### Notes

- `--shm-size=1g` is required for Chromium to work properly in Docker
- The image is ~1.2GB (Playwright base + Chromium)
- First tool call takes ~30s (browser auth), subsequent calls are fast (~1-3s)
