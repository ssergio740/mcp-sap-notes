# Debug Output Reference for search

## Quick Reference

When you run `npm run start:http:debug`, you'll see detailed debug output for every search operation using SAP's Coveo Search API.

## Log Levels

| Symbol | Level | Description |
|--------|-------|-------------|
| 🔎 | INFO | Search operation started |
| 🔍 | INFO | SAP Notes search initiated |
| 📊 | DEBUG | Parameters and data details |
| 🔄 | DEBUG | Trying different search methods |
| 🌐 | DEBUG | HTTP request to external API |
| 📥 | DEBUG | HTTP response received |
| ✅ | INFO | Success |
| ⚠️  | WARN | Warning or fallback |
| ❌ | WARN/ERROR | Failure |
| 📄 | DEBUG | Results data |
| 📤 | DEBUG | Return message preview |

## Example: Searching by Note Number via Coveo

### User Query: `"2744792"`

```
[14:23:15] INFO: 🔎 [handleSapNoteSearch] Starting search for query: "2744792"
[14:23:15] INFO: 🔍 Searching SAP Notes for: "2744792"
[14:23:15] DEBUG: 📊 Search parameters: query="2744792", maxResults=10
[14:23:15] DEBUG: 🔑 Fetching Coveo bearer token from SAP session
[14:23:15] DEBUG: ✅ Successfully extracted Coveo token from SAP page
[14:23:15] DEBUG: 🌐 Coveo Search URL: https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2?organizationId=sapamericaproductiontyfzmfz0
[14:23:15] DEBUG: 📤 Coveo Search Body: {"locale":"en-US","debug":false,"tab":"All","referrer":"SAP for Me search interface","q":"2744792","numberOfResults":10,"facets":[{"field":"documenttype","currentValues":[{"value":"SAP Note","state":"selected"}]}]...
[14:23:16] DEBUG: 📊 Coveo Response: 200 OK
[14:23:16] DEBUG: 📄 Coveo Results: 1 results found
[14:23:16] INFO: ✅ Found 1 SAP Note(s) via Coveo
[14:23:16] DEBUG: 📄 Search results: [
  {
    "id": "2744792",
    "title": "Java Applications work with keystore \"DEFAULT\" and SAP Cloud Connector"
  }
]
[14:23:16] DEBUG: 📤 [handleSapNoteSearch] Return message preview:
Found 1 SAP Note(s) for query: "2744792"

**SAP Note 2744792**
Title: Java Applications work with keystore "DEFAULT" and SAP Cloud Connector
Summary: Applications using SAP JCo or JDBC fail with security exceptions when connecting through SAP Cloud...
[14:23:16] INFO: ✅ [handleSapNoteSearch] Successfully completed search, returning 1 results
```

**URLs Queried:**
- ✅ Token extraction: `https://me.sap.com/search` (200 OK)
- ✅ Coveo search: `https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2?organizationId=sapamericaproductiontyfzmfz0` (200 OK)

---

## Example: Searching by Keyword via Coveo

### User Query: `"authorization error"`

```
[14:25:30] INFO: 🔎 [handleSapNoteSearch] Starting search for query: "authorization error"
[14:25:30] INFO: 🔍 Searching SAP Notes for: "authorization error"
[14:25:30] DEBUG: 📊 Search parameters: query="authorization error", maxResults=10
[14:25:30] DEBUG: 🔑 Fetching Coveo bearer token from SAP session
[14:25:30] DEBUG: ✅ Successfully extracted Coveo token from SAP page
[14:25:30] DEBUG: 🌐 Coveo Search URL: https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2?organizationId=sapamericaproductiontyfzmfz0
[14:25:30] DEBUG: 📤 Coveo Search Body: {"locale":"en-US","q":"authorization error","numberOfResults":10,"facets":[{"field":"documenttype","currentValues":[{"value":"SAP Note","state":"selected"}]}]...
[14:25:31] DEBUG: 📊 Coveo Response: 200 OK
[14:25:31] DEBUG: 📄 Coveo Results: 3 results found
[14:25:31] INFO: ✅ Found 3 SAP Note(s) via Coveo
[14:25:31] DEBUG: 📄 Search results: [
  {
    "id": "3089413",
    "title": "Authorization error in SAP Fiori Launchpad"
  },
  {
    "id": "2817314",
    "title": "User authorization issue in SAP Gateway"
  },
  {
    "id": "2456789",
    "title": "Authorization check failed in CDS view"
  }
]
[14:25:31] DEBUG: 📤 [handleSapNoteSearch] Return message preview:
Found 3 SAP Note(s) for query: "authorization error"

**SAP Note 3089413**
Title: Authorization error in SAP Fiori Launchpad
Summary: Users receive authorization error when accessing Fiori apps...
[14:25:31] INFO: ✅ [handleSapNoteSearch] Successfully completed search, returning 3 results
```

**URLs Queried:**
- ✅ Token extraction: `https://me.sap.com/search` (200 OK)
- ✅ Coveo search with natural language query (200 OK)

---

## Example: No Results Found

### User Query: `"xyzabc123nonexistent"`

```
[14:27:45] INFO: 🔎 [handleSapNoteSearch] Starting search for query: "xyzabc123nonexistent"
[14:27:45] INFO: 🔍 Searching SAP Notes for: "xyzabc123nonexistent"
[14:27:45] DEBUG: 📊 Search parameters: query="xyzabc123nonexistent", maxResults=10
[14:27:45] DEBUG: 🔑 Fetching Coveo bearer token from SAP session
[14:27:45] DEBUG: ✅ Successfully extracted Coveo token from SAP page
[14:27:45] DEBUG: 🌐 Coveo Search URL: https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2?organizationId=sapamericaproductiontyfzmfz0
[14:27:45] DEBUG: 📤 Coveo Search Body: {"locale":"en-US","q":"xyzabc123nonexistent","numberOfResults":10...
[14:27:46] DEBUG: 📊 Coveo Response: 200 OK
[14:27:46] DEBUG: 📄 Coveo Results: 0 results found
[14:27:46] WARN: ⚠️ No results array in Coveo response
[14:27:46] INFO: ✅ Found 0 SAP Note(s) via Coveo
[14:27:46] INFO: ✅ [handleSapNoteSearch] Successfully completed search, returning 0 results
```

**URLs Queried:**
- ✅ Token extraction: `https://me.sap.com/search` (200 OK)
- ✅ Coveo search (200 OK, 0 results)

---

## Return Message Structure

The tool returns a JSON-RPC response with this structure:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Found 1 SAP Note(s) for query: \"2744792\"\n\n**SAP Note 2744792**\nTitle: Java Applications work with keystore \"DEFAULT\" and SAP Cloud Connector\nSummary: Applications using SAP JCo or JDBC fail with security exceptions\nComponent: BC-MID-CON-JCO\nRelease Date: 2019-03-15\nLanguage: EN\nURL: https://launchpad.support.sap.com/#/notes/2744792\n\n"
      }
    ],
    "isError": false
  }
}
```

---

## Key External URLs

### Primary URLs Queried:

1. **Coveo Token Extraction:**
   ```
   GET https://me.sap.com/search
   ```
   Purpose: Extract the Coveo bearer token from SAP session

2. **Coveo Search API:**
   ```
   POST https://sapamericaproductiontyfzmfz0.org.coveo.com/rest/search/v2?organizationId=sapamericaproductiontyfzmfz0
   ```
   Purpose: Search SAP Notes using Coveo's powerful search engine
   
   Request Body:
   ```json
   {
     "q": "search query",
     "numberOfResults": 10,
     "locale": "en-US",
     "searchHub": "SAP for Me",
     "facets": [
       {
         "field": "documenttype",
         "currentValues": [{"value": "SAP Note", "state": "selected"}]
       }
     ],
     "fieldsToInclude": ["mh_id", "mh_description", "mh_category", "mh_alt_url"]
   }
   ```

3. **Note Details (for fetch):**
   ```
   GET https://me.sap.com/backend/raw/sapnotes/Detail?q={noteId}&t=E&isVTEnabled=false
   ```

---

## How to Enable Debug Mode

### Start the server in debug mode:
```bash
npm run start:http:debug
```

This sets:
- `LOG_LEVEL=debug` - Shows all log levels
- `HTTP_PORT=3123` - Runs on port 3123
- `DEBUG_START=true` - Shows startup diagnostics

### Test with curl:
```bash
# Initialize
curl -X POST http://localhost:3123/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}'

# Search for a note
curl -X POST http://localhost:3123/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"search",
      "arguments":{"q":"2744792"}
    }
  }'
```

### Watch logs:
All debug output goes to **stderr**, so you can:
```bash
npm run start:http:debug 2>&1 | tee debug.log
```

---

## Summary

✅ **What you get with debug mode:**
- Full URL of every API request
- HTTP status codes of responses
- Search strategy progression (note number → keyword → general)
- Detailed result data (IDs, titles)
- Preview of the return message
- Timing information

✅ **Search flow visibility:**
1. See which search method is tried first
2. See why it fails or succeeds
3. See fallback to next method
4. See final results

✅ **Debugging capabilities:**
- Trace exact URLs being called
- Identify which API endpoints are responding
- Understand search strategy decisions
- Verify return message format

