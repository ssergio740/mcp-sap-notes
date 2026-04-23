# Setup Guide

## Prerequisites

- Python 3.10+
- `pip`
- An SAP S-user account with access to SAP Notes

## Installation

```bash
git clone https://github.com/marianfoo/mcp-sap-notes.git
cd mcp-sap-notes
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -e .
python -m playwright install chromium
```

## Configuration

Create a `.env` file with either username/password or certificate credentials.

### Username / Password

```env
SAP_USERNAME=your.email@company.com
SAP_PASSWORD=your_sap_password
```

### Certificate

```env
PFX_PATH=./certs/sap.pfx
PFX_PASSPHRASE=your_certificate_passphrase
```

### HTTP Mode

```env
MCP_SERVER_URL=https://your-public-host.example.com/mcp
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-app-client-id
AZURE_CLIENT_SECRET=your-app-client-secret
AZURE_REQUIRED_SCOPES=access_as_user
ALLOWED_EMAIL_DOMAINS=company.com,partner.com
```

## Run

```bash
mcp-sap-notes-stdio
mcp-sap-notes-http
```

## Docker

```bash
docker build -t mcp-sap-notes-python .
docker run -d --name mcp-sap-notes \
  --shm-size=1g \
  -p 3123:3123 \
  -e SAP_USERNAME=your.email@company.com \
  -e SAP_PASSWORD=your_sap_password \
  -e MCP_SERVER_URL=https://your-public-host.example.com/mcp \
  -e AZURE_TENANT_ID=your-tenant-id \
  -e AZURE_CLIENT_ID=your-app-client-id \
  -e AZURE_CLIENT_SECRET=your-app-client-secret \
  -e ALLOWED_EMAIL_DOMAINS=company.com,partner.com \
  mcp-sap-notes-python
```
