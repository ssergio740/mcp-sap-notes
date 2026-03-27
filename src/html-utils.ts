/**
 * Utilities for extracting clean text and structured sections from SAP Note HTML content.
 * SAP Notes use <h3 class="section" id="SectionName"> headers to delimit sections.
 */

export interface NoteSection {
  heading: string;
  content: string;
}

export interface ParsedNoteContent {
  /** Extracted sections (Symptom, Solution, etc.) */
  sections: NoteSection[];
  /** Plain-text rendering of the full note (for LLMs) */
  plainText: string;
}

/**
 * Strip HTML tags and decode entities, producing clean plain text.
 */
export function stripHtml(html: string): string {
  return html
    // Replace <br> / <br/> with newlines
    .replace(/<br\s*\/?>/gi, '\n')
    // Replace </p>, </li>, </div>, </h3> with newlines
    .replace(/<\/(p|li|div|h[1-6]|tr)>/gi, '\n')
    // Replace </ol>, </ul> with newline
    .replace(/<\/(ol|ul)>/gi, '\n')
    // Replace <li> with bullet
    .replace(/<li[^>]*>/gi, '- ')
    // Remove <img> tags but keep alt text if present
    .replace(/<img[^>]*alt="([^"]*)"[^>]*>/gi, '[$1]')
    .replace(/<img[^>]*>/gi, '')
    // Remove all remaining tags
    .replace(/<[^>]+>/g, '')
    // Decode HTML entities
    .replace(/&#x00A0;/g, ' ')
    .replace(/&#34;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&nbsp;/g, ' ')
    .replace(/&#\d+;/g, '') // remaining numeric entities
    .replace(/&[a-z]+;/gi, '') // remaining named entities
    // Clean up whitespace
    .replace(/[ \t]+/g, ' ')
    .replace(/\n[ \t]+/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

/**
 * Parse SAP Note HTML content into structured sections.
 * SAP Notes use: <h3 ... id="SectionName">SectionName</h3> followed by content.
 */
export function parseNoteSections(html: string): NoteSection[] {
  const sections: NoteSection[] = [];

  // Split on <h3> section headers
  // Pattern: <h3 ... class="section" ... id="SectionName">SectionName</h3>
  const sectionRegex = /<h3[^>]*class="section"[^>]*id="([^"]*)"[^>]*>([^<]*)<\/h3>/gi;
  const matches = [...html.matchAll(sectionRegex)];

  if (matches.length === 0) {
    // No structured sections found — return entire content as one section
    const text = stripHtml(html);
    if (text) {
      sections.push({ heading: 'Content', content: text });
    }
    return sections;
  }

  for (let i = 0; i < matches.length; i++) {
    const match = matches[i];
    const heading = match[2].trim() || match[1].trim();
    const startIndex = match.index! + match[0].length;
    const endIndex = i + 1 < matches.length ? matches[i + 1].index! : html.length;

    const sectionHtml = html.substring(startIndex, endIndex);
    const content = stripHtml(sectionHtml);

    if (content) {
      sections.push({ heading, content });
    }
  }

  return sections;
}

/**
 * Parse HTML and return both structured sections and a clean plain-text rendering.
 */
export function parseNoteContent(html: string): ParsedNoteContent {
  const sections = parseNoteSections(html);

  // Build plain text with section headers
  const plainText = sections
    .map(s => `## ${s.heading}\n${s.content}`)
    .join('\n\n');

  return { sections, plainText };
}
