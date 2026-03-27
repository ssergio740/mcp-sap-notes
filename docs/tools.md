# MCP Tools Reference

## `sap_note_search`

Search the SAP Knowledge Base (SAP Notes) for troubleshooting articles, bug fixes, patches, corrections, and known issues.

### Input

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `q` | string | Yes | - | Search query (2-200 chars) |
| `lang` | `'EN'` \| `'DE'` | No | `'EN'` | Language for results |

### Output

```typescript
{
  totalResults: number;
  query: string;
  results: Array<{
    id: string;          // Note ID (e.g., "2744792")
    title: string;       // Note title
    summary: string;     // Brief description
    component: string | null;  // SAP component (e.g., "CA-UI5")
    releaseDate: string; // ISO date
    language: string;    // "EN" or "DE"
    url: string;         // SAP Support Portal URL
  }>;
}
```

### Query Tips

Effective queries follow this formula: `[Error Code/Transaction] + [Module/Component] + [Issue Type]`

**Good queries:**
- `"OData gateway error 415"` - Error code + context
- `"MM02 material master dump"` - Transaction + module + issue
- `"ABAP CX_SY_ZERODIVIDE"` - Specific exception
- `"S/4HANA migration performance"` - Product + issue
- `"2744792"` - Direct note ID lookup

**Bad queries:**
- `"SAP problem"` - Too vague
- `"not working"` - No specifics
- `"help"` - No context

### Search Strategy

The tool uses a multi-tier fallback:
1. **Coveo Search API** - SAP's primary search engine (ranked by relevance)
2. **Direct Note ID** - If query matches `^\d{6,8}$`, tries direct lookup
3. **SAP Internal Search** - Bypasses Coveo as last resort

---

## `sap_note_get`

Fetch the complete content and metadata for a specific SAP Note by ID.

### Input

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `id` | string | Yes | - | Note ID (alphanumeric) |
| `lang` | `'EN'` \| `'DE'` | No | `'EN'` | Language for content |

### Output

```typescript
{
  id: string;
  title: string;
  summary: string;
  component: string | null;
  priority: string | null;     // "Very High", "High", "Medium", "Low"
  category: string | null;     // "Correction", "Consulting", etc.
  releaseDate: string;
  language: string;
  url: string;
  content: string;             // Full HTML content
}
```

### Content Structure

SAP Note content typically includes these sections:
- **Symptom** - Problem description
- **Reason and Prerequisites** - Root cause
- **Solution** - Step-by-step fix instructions
- **Affected Releases** - Impacted SAP versions
- **Related Notes** - Cross-references

### Retrieval Strategy

1. **Playwright Raw Notes API** - Browser-based extraction (primary)
2. **HTTP Raw Notes API** - Direct HTTP fetch (fallback)

---

## Recommended Workflow

For best results, chain search and get:

```
1. sap_note_search(q="OData 415 error CAP")
   → Returns: [{id: "2744792", title: "..."}, {id: "438342", ...}]

2. sap_note_get(id="2744792")
   → Returns: Full note with solution steps

3. Synthesize answer from note content
```

- Review first 2-5 search results
- Fetch details for top 2-3 most relevant notes
- Do NOT fetch all results
