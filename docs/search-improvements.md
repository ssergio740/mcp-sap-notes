# Search & Fetch Improvement Analysis

## Current Implementation

### Search Flow
1. **Primary**: Coveo Search API via direct HTTP (`getCoveoTokenDirect` → POST to Coveo)
2. **Fallback 1**: Coveo token via Playwright (browser loads search page, intercepts token)
3. **Fallback 2**: Direct note ID lookup (if query is 6-8 digits)
4. **Fallback 3**: SAP Internal Search API

### Fetch Flow
1. **Primary**: Playwright browser navigates to raw notes API endpoint
2. **Fallback 1**: Direct HTTP fetch to raw notes API
3. **Fallback 2**: OData endpoints on launchpad.support.sap.com
4. **Fallback 3**: HTML scraping from support portal

## Identified Improvement Areas

### 1. Coveo Token Caching
**Problem**: The Coveo bearer token is fetched fresh for every search request. This adds latency (network round-trip) and can fail if SAP session is slow.

**Improvement**: Cache the Coveo token alongside the session cookies. The Coveo token typically has a TTL of 15-30 minutes.

```typescript
// Add to SapNotesApiClient
private coveoTokenCache: { token: string; expiresAt: number } | null = null;

private async getCoveoToken(sapToken: string): Promise<string> {
  if (this.coveoTokenCache && Date.now() < this.coveoTokenCache.expiresAt) {
    return this.coveoTokenCache.token;
  }
  const token = await this.getCoveoTokenDirect(sapToken);
  this.coveoTokenCache = { token, expiresAt: Date.now() + 15 * 60 * 1000 };
  return token;
}
```

### 2. Search Result Quality
**Problem**: Coveo search body construction is hardcoded. Advanced query syntax (AQS) could improve relevance.

**Improvement options**:
- Use Coveo's `aq` (advanced query) field for better filtering
- Add `dq` (disjunction query) for broader matching
- Use `cq` (constant query) for persistent filters
- Add component-based filtering when user mentions SAP module names

### 3. Content Extraction
**Problem**: `getNote()` returns raw HTML. The LLM then needs to parse it. Large HTML content wastes tokens.

**Improvement**: Pre-process HTML before returning:
- Strip HTML tags, keep structure
- Extract key sections (Symptom, Solution, Affected Releases)
- Limit content length with intelligent truncation
- Return structured sections instead of raw HTML blob

### 4. Browser Session Reuse
**Problem**: The Playwright browser for note retrieval has a 5-minute idle timeout. Every search that triggers the Playwright fallback launches a new browser.

**Improvement**: Share browser sessions between the search Playwright fallback and note retrieval. Use a single browser pool.

### 5. Parallel Note Retrieval
**Problem**: When the LLM calls `sap_note_get` for multiple notes, they run sequentially.

**Improvement**: The MCP protocol handles this at the client level, but the tool descriptions could suggest batching. A `sap_notes_get_batch` tool accepting multiple IDs could reduce round-trips.

### 6. Search Suggestions
**Problem**: When search returns 0 results, the user gets a generic error. There's no guidance on how to refine the query.

**Improvement**: When 0 results are found:
- Suggest alternative query formulations
- Try simplified query (remove stop words)
- Check if the query might be a note ID or transaction code
- Suggest using `sap_note_get` directly if it looks like an ID

### 7. Structured Content Sections
**Problem**: The `content` field in note details is a single HTML string. The LLM needs to parse sections manually.

**Improvement**: Return content as structured sections:
```typescript
interface NoteContent {
  symptom?: string;
  reason?: string;
  solution?: string;
  affectedReleases?: string[];
  relatedNotes?: string[];
  additionalInfo?: string;
  raw: string;  // Original HTML as fallback
}
```

## Priority Recommendations

| Priority | Improvement | Effort | Impact |
|----------|-------------|--------|--------|
| High | Coveo token caching | Low | Faster search, fewer failures |
| High | Content extraction / HTML stripping | Medium | Better LLM responses, fewer tokens |
| Medium | Structured content sections | Medium | Better LLM comprehension |
| Medium | Search suggestions on 0 results | Low | Better user experience |
| Low | Browser session pooling | High | Performance optimization |
| Low | Batch note retrieval | Medium | Power user feature |

## Next Steps

These improvements can be implemented incrementally. The Coveo token caching and content extraction are the highest-value changes to tackle first.
