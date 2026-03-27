import { config } from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join, isAbsolute } from 'path';
import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import type { ServerConfig } from './types.js';
import { SapAuthenticator } from './auth.js';
import { SapNotesApiClient } from './sap-notes-api.js';
import { logger } from './logger.js';
import {
  NoteSearchInputSchema,
  NoteSearchOutputSchema,
  NoteGetInputSchema,
  NoteGetOutputSchema,
  SAP_NOTE_SEARCH_DESCRIPTION,
  SAP_NOTE_GET_DESCRIPTION
} from './schemas/sap-notes.js';
import { parseNoteContent } from './html-utils.js';

// Get the directory of this module for resolving paths
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load environment variables from the project root
config({ path: join(__dirname, '..', '.env') });

/**
 * SAP Note MCP Server using the MCP SDK
 * This implementation uses enhanced tool descriptions for improved LLM accuracy
 */
class SapNoteMcpServer {
  private config: ServerConfig;
  private authenticator: SapAuthenticator;
  private sapNotesClient: SapNotesApiClient;
  private mcpServer: McpServer;

  constructor() {
    this.config = this.loadConfig();
    this.authenticator = new SapAuthenticator(this.config);
    this.sapNotesClient = new SapNotesApiClient(this.config);
    
    // Create MCP server with official SDK
    this.mcpServer = new McpServer({
      name: 'sap-note-search-mcp',
      version: '0.3.0'
    });

    this.setupTools();
  }

  /**
   * Load configuration from environment variables
   */
  private loadConfig(): ServerConfig {
    // Determine auth method
    const authMethod = (process.env.AUTH_METHOD || 'auto') as 'certificate' | 'password' | 'auto';
    const sapUsername = process.env.SAP_USERNAME;
    const sapPassword = process.env.SAP_PASSWORD;
    const hasCertConfig = !!(process.env.PFX_PATH && process.env.PFX_PASSPHRASE);
    const hasPasswordConfig = !!(sapUsername && sapPassword);

    // Validate that at least one auth method is configured
    if (!hasCertConfig && !hasPasswordConfig) {
      throw new Error(
        'No authentication configured. Set either SAP_USERNAME + SAP_PASSWORD for password auth, ' +
        'or PFX_PATH + PFX_PASSPHRASE for certificate auth.'
      );
    }

    // Resolve PFX path (may be empty if using password auth)
    const projectRoot = join(__dirname, '..');
    let pfxPath = process.env.PFX_PATH || '';

    if (pfxPath) {
      if (pfxPath.startsWith('~')) {
        const home = process.env.HOME || process.env.USERPROFILE || '';
        pfxPath = join(home, pfxPath.slice(2));
      }
      if (!isAbsolute(pfxPath)) {
        pfxPath = join(projectRoot, pfxPath);
      }
    }

    // Detect Docker/container environment
    const isDocker = process.env.DOCKER_ENV === 'true' ||
                    process.env.NODE_ENV === 'production' ||
                    !process.env.DISPLAY ||
                    !process.stdin.isTTY ||
                    process.env.CI === 'true';

    const headful = !isDocker && process.env.HEADFUL === 'true';

    logger.warn('Configuration loaded:', {
      authMethod,
      hasPassword: hasPasswordConfig,
      hasCertificate: hasCertConfig,
      headful
    });

    return {
      pfxPath,
      pfxPassphrase: process.env.PFX_PASSPHRASE || '',
      sapUsername,
      sapPassword,
      authMethod,
      mfaTimeout: parseInt(process.env.MFA_TIMEOUT || '120000'),
      maxJwtAgeH: parseInt(process.env.MAX_JWT_AGE_H || '12'),
      headful,
      logLevel: process.env.LOG_LEVEL || 'info'
    };
  }

  /**
   * Execute an API call with automatic auth retry on session expiry.
   * If the call fails with a session/auth error, invalidates the token and retries once.
   */
  private async withAuthRetry<T>(fn: (token: string) => Promise<T>): Promise<T> {
    const token = await this.authenticator.ensureAuthenticated();
    try {
      return await fn(token);
    } catch (error) {
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes('SESSION_EXPIRED') || msg.includes('401') || msg.includes('Unauthorized') || msg.includes('session expired')) {
        logger.warn('Session expired, re-authenticating and retrying...');
        this.authenticator.invalidateAuth();
        const newToken = await this.authenticator.ensureAuthenticated();
        return await fn(newToken);
      }
      throw error;
    }
  }

  /**
   * Setup MCP tools using the official SDK
   */
  private setupTools(): void {
    // SAP Note Search Tool
    this.mcpServer.registerTool(
      'sap_note_search',
      {
        title: 'Search SAP Notes',
        description: SAP_NOTE_SEARCH_DESCRIPTION,
        inputSchema: NoteSearchInputSchema,
        outputSchema: NoteSearchOutputSchema
      },
      async ({ q, lang = 'EN' }) => {
        logger.info(`🔎 [sap_note_search] Starting search for query: "${q}"`);
        
        try {
          const searchResponse = await this.withAuthRetry(token =>
            this.sapNotesClient.searchNotes(q, token, 10)
          );

          // Format results
          const output = {
            totalResults: searchResponse.totalResults,
            query: searchResponse.query,
            results: searchResponse.results.map(note => ({
              id: note.id,
              title: note.title,
              summary: note.summary,
              component: note.component || null,
              releaseDate: note.releaseDate,
              language: note.language,
              url: note.url
            }))
          };

          // Format display text
          let resultText = `Found ${output.totalResults} SAP Note(s) for query: "${output.query}"\n\n`;
          
          for (const note of output.results) {
            resultText += `**SAP Note ${note.id}**\n`;
            resultText += `Title: ${note.title}\n`;
            resultText += `Summary: ${note.summary}\n`;
            resultText += `Component: ${note.component || 'Not specified'}\n`;
            resultText += `Release Date: ${note.releaseDate}\n`;
            resultText += `Language: ${note.language}\n`;
            resultText += `URL: ${note.url}\n\n`;
          }

          logger.info(`✅ [sap_note_search] Successfully completed search, returning ${output.totalResults} results`);

          return {
            content: [{ type: 'text', text: resultText }],
            structuredContent: output
          };

        } catch (error) {
          logger.error('❌ Search failed:', error);
          const errorMessage = error instanceof Error ? error.message : 'Unknown search error';
          
          return {
            content: [{ 
              type: 'text', 
              text: `Search failed: ${errorMessage}` 
            }],
            isError: true
          };
        }
      }
    );

    // SAP Note Get Tool
    this.mcpServer.registerTool(
      'sap_note_get',
      {
        title: 'Get SAP Note Details',
        description: SAP_NOTE_GET_DESCRIPTION,
        inputSchema: NoteGetInputSchema,
        outputSchema: NoteGetOutputSchema
      },
      async ({ id, lang = 'EN' }) => {
        logger.info(`📄 [sap_note_get] Getting note details for ID: ${id}`);
        
        try {
          const noteDetail = await this.withAuthRetry(token =>
            this.sapNotesClient.getNote(id, token)
          );

          if (!noteDetail) {
            return {
              content: [{ 
                type: 'text', 
                text: `SAP Note ${id} not found or not accessible.` 
              }],
              isError: true
            };
          }

          // Parse HTML content into clean text with sections
          const parsed = parseNoteContent(noteDetail.content);

          // Structure the output — use plain text instead of raw HTML
          const output = {
            id: noteDetail.id,
            title: noteDetail.title,
            summary: noteDetail.summary,
            component: noteDetail.component || null,
            priority: noteDetail.priority || null,
            category: noteDetail.category || null,
            releaseDate: noteDetail.releaseDate,
            language: noteDetail.language,
            url: noteDetail.url,
            content: parsed.plainText || noteDetail.content
          };

          // Format display text
          let resultText = `**SAP Note ${output.id} - ${output.title}**\n\n`;
          resultText += `Component: ${output.component || 'Not specified'} | `;
          resultText += `Priority: ${output.priority || 'Not specified'} | `;
          resultText += `Released: ${output.releaseDate}\n`;
          resultText += `URL: ${output.url}\n\n`;
          resultText += output.content + '\n';

          logger.info(`✅ [sap_note_get] Successfully retrieved note ${id}`);

          return {
            content: [{ type: 'text', text: resultText }],
            structuredContent: output
          };

        } catch (error) {
          logger.error(`❌ Note retrieval failed for ${id}:`, error);
          const errorMessage = error instanceof Error ? error.message : 'Unknown retrieval error';
          
          return {
            content: [{ 
              type: 'text', 
              text: `Failed to retrieve SAP Note ${id}: ${errorMessage}` 
            }],
            isError: true
          };
        }
      }
    );
  }

  /**
   * Start the MCP server with stdio transport
   */
  async start(): Promise<void> {
    logger.warn('🚀 Starting SAP Note MCP Server');
    
    try {
      // Create stdio transport
      const transport = new StdioServerTransport();
      
      // Connect server to transport
      await this.mcpServer.connect(transport);
      
      logger.warn('✅ MCP Server connected and ready');
      
    } catch (error) {
      logger.error('❌ Failed to start MCP server:', error);
      throw error;
    }
  }

  /**
   * Graceful shutdown
   */
  async shutdown(): Promise<void> {
    logger.info('Shutting down MCP server...');
    try {
      await this.authenticator.destroy();
      logger.info('Server shutdown completed');
    } catch (error) {
      logger.error('Error during shutdown:', error);
    }
  }
}

// Start server if this file is run directly (ESM-safe, cross-platform)
const isDirectRun = (() => {
  try {
    const thisFile = fileURLToPath(import.meta.url);
    const invoked = process.argv[1] ? process.argv[1] : '';
    return thisFile === invoked;
  } catch {
    return false;
  }
})();

if (isDirectRun) {
  const server = new SapNoteMcpServer();
  
  // Handle process termination gracefully
  process.on('SIGINT', () => server.shutdown().then(() => process.exit(0)));
  process.on('SIGTERM', () => server.shutdown().then(() => process.exit(0)));
  
  server.start().catch((error) => {
    logger.error('Failed to start server:', error);
    process.exit(1);
  });
}

export { SapNoteMcpServer };







