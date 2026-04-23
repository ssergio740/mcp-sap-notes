# Authentication

The server supports two authentication methods for accessing SAP's services. Both use Playwright browser automation to obtain session cookies.

## Authentication Methods

### 1. Username/Password Authentication (Recommended)

The most stable and automatable method. Works well in headless environments without 2FA, or with 2FA in headful mode.

**Configuration:**
```env
SAP_USERNAME=your.email@company.com
SAP_PASSWORD=your_sap_password
AUTH_METHOD=password   # or 'auto' (default)
```

If you omit `SAP_USERNAME` and `SAP_PASSWORD`, the server can prompt for them only in local stdio sessions with an interactive terminal. In HTTP/AWS deployments, the credentials are collected during the SAP registration step after Microsoft login and stored encrypted per user.

**MCP Client Config (Cursor / Claude Desktop):**
```json
{
  "mcpServers": {
    "sap-notes": {
      "command": "mcp-sap-notes-stdio",
      "env": {
        "SAP_USERNAME": "your.email@company.com",
        "SAP_PASSWORD": "your_sap_password"
      }
    }
  }
}
```

**How it works:**
1. Browser navigates to `me.sap.com/home`
2. Redirected to SAP IAS login page (`accounts.sap.com`)
3. Username field detected and filled (tries multiple CSS selectors)
4. Handles both single-page and multi-step login flows
5. Password field filled and form submitted
6. If MFA/2FA is required, waits for manual code entry (configurable timeout)
7. Session cookies extracted after successful redirect

**Advantages:**
- No certificate management required
- Credentials are stored per Microsoft user, not globally
- Works in CI/CD pipelines and AWS deployments
- The server can keep access control tied to SAP credential validation

### 2. Certificate Authentication

Uses a `.pfx` client certificate for automatic authentication via TLS handshake.

**Configuration:**
```json
{
  "mcpServers": {
    "sap-notes": {
      "command": "mcp-sap-notes-stdio",
      "env": {
        "SAP_USERNAME": "your.email@company.com",
        "SAP_PASSWORD": "your_sap_password"
      }
    }
  }
}
```
- No password storage required
- Automatic auth without form interaction
- Works well when certificate is valid and accessible

**Getting a certificate:**
1. Log into [SAP Support Portal](https://launchpad.support.sap.com)
2. Navigate to your profile/settings
3. Download your SAP Passport certificate as `.pfx` format
4. Place it in the `certs/` directory
5. Set the passphrase in your `.env` file

## Auto Mode (Default)

When `AUTH_METHOD=auto` (the default), the server automatically selects:

1. **Password auth** if `SAP_USERNAME` + `SAP_PASSWORD` are set
2. **Certificate auth** if `PFX_PATH` + `PFX_PASSPHRASE` are set
3. **Password auth with interactive prompts** only for local stdio runs with a TTY

## AWS / Claude Flow

In the AWS deployment pattern, Claude authenticates to the MCP server through Microsoft OAuth when connecting to the HTTP endpoint. After Microsoft login, the server checks whether SAP credentials already exist for that Microsoft user. If not, it shows the SAP registration form in the browser, validates the credentials against SAP, and stores them encrypted.

The encrypted credential store is configured with:

```env
SAP_CRED_STORE_PATH=sap_credentials.json
SAP_CRED_ENCRYPTION_KEY=your-fernet-key
```

If `SAP_CRED_ENCRYPTION_KEY` is omitted, the server generates a temporary key and logs a warning. Persist the key in AWS Secrets Manager, SSM Parameter Store, or the container environment so stored credentials survive restarts.

## MFA/2FA Support

Both authentication methods support Multi-Factor Authentication:

- **MFA_TIMEOUT**: How long to wait for 2FA code entry (default: 120000ms = 2 minutes)
- **HEADFUL=true**: Required to see the browser window for manual 2FA entry
- 2FA detection covers: TOTP, passcode, verification pages

If you have 2FA enabled on your SAP account:
```env
HEADFUL=true
MFA_TIMEOUT=120000
```

When 2FA is detected, the server logs a message asking you to complete authentication in the browser window.

## Token Caching

After successful authentication, session cookies are cached to `token-cache.json`:

```json
{
  "access_token": "cookie1=val1; cookie2=val2; ...",
  "cookies": [{"name": "...", "value": "...", "domain": "..."}],
  "expiresAt": 1234567890000
}
```

- Default TTL: 12 hours (configurable via `MAX_JWT_AGE_H`)
- 5-minute buffer before expiry triggers re-authentication
- Delete `token-cache.json` to force fresh authentication

## Troubleshooting

### "Could not find username field"
- The SAP login page layout may have changed
- Try `HEADFUL=true` and take a screenshot to see the page
- Check if you're being redirected to a different IdP

### "Authentication timed out"
- Check internet connectivity
- Verify SAP services are accessible
- Increase `MFA_TIMEOUT` if using 2FA
- Try `HEADFUL=true` to see what's happening

### "Certificate load failed"
- Verify the `.pfx` file exists at the configured path
- Check the passphrase is correct
- Ensure the certificate hasn't expired

### Browser launch failures
- Install Playwright browsers: `python -m playwright install chromium`
- Docker: ensure system dependencies are installed
- Check the [Playwright system requirements](https://playwright.dev/docs/intro#system-requirements)

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SAP_USERNAME` | - | SAP login username (email) |
| `SAP_PASSWORD` | - | SAP login password |
| `PFX_PATH` | - | Path to .pfx certificate file |
| `PFX_PASSPHRASE` | - | Certificate passphrase |
| `AUTH_METHOD` | `auto` | `auto`, `password`, or `certificate` |
| `MFA_TIMEOUT` | `120000` | MFA wait timeout in ms |
| `MAX_JWT_AGE_H` | `12` | Token cache lifetime in hours |
| `HEADFUL` | `false` | Show browser window (required for 2FA) |
