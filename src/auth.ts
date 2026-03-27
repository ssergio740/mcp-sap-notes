import { chromium, firefox, webkit, type Browser, type BrowserContext, type Page } from 'playwright';
import { writeFileSync, existsSync, readFileSync } from 'fs';
import type { AuthState, ServerConfig } from './types.js';
import { logger } from './logger.js';

const TOKEN_CACHE_FILE = 'token-cache.json';

/**
 * Custom error classes for better error handling
 */
class BrowserNotFoundError extends Error {
  constructor(browserType: string, searchPaths: string[] = []) {
    super(`Browser ${browserType} not found${searchPaths.length ? ` in paths: ${searchPaths.join(', ')}` : ''}`);
    this.name = 'BrowserNotFoundError';
  }
}

class CertificateLoadError extends Error {
  constructor(certPath: string, originalError: Error) {
    super(`Failed to load certificate from ${certPath}: ${originalError.message}`);
    this.name = 'CertificateLoadError';
  }
}

class AuthenticationTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`Authentication timed out after ${timeoutMs}ms`);
    this.name = 'AuthenticationTimeoutError';
  }
}

class AuthenticationError extends Error {
  originalError?: Error;

  constructor(message: string, originalError?: Error) {
    super(message);
    this.name = 'AuthenticationError';
    this.originalError = originalError;
  }
}

export class SapAuthenticator {
  private authState: AuthState = { isAuthenticated: false };
  private authPromise: Promise<void> | null = null;
  private browser: Browser | null = null;
  private context: BrowserContext | null = null;
  private page: Page | null = null;

  constructor(private config: ServerConfig) {}

  /**
   * Ensures authentication is valid, performing login if needed
   * Includes single-flight guard to prevent concurrent authentication attempts
   */
  async ensureAuthenticated(): Promise<string> {
    // Single-flight guard - if authentication is in progress, wait for it
    if (this.authPromise) {
      await this.authPromise;
    }

    // Check if current token is still valid
    if (this.isTokenValid()) {
      return this.authState.token!;
    }

    // Start new authentication flow
    this.authPromise = this.authenticate();
    await this.authPromise;
    this.authPromise = null;

    if (!this.authState.token) {
      throw new Error('Authentication failed - no token received');
    }

    return this.authState.token;
  }

  /**
   * Invalidate current authentication and force fresh login
   * Call this when session cookies have expired or been rejected by SAP
   */
  invalidateAuth(): void {
    logger.warn('Invalidating cached authentication');
    this.authState = { isAuthenticated: false };
  }

  /**
   * Check if the current token is valid and not expired
   */
  private isTokenValid(): boolean {
    if (!this.authState.token || !this.authState.expiresAt) {
      return false;
    }

    // Add 5 minute buffer before expiry
    const bufferMs = 5 * 60 * 1000;
    return Date.now() < (this.authState.expiresAt - bufferMs);
  }

  /**
   * Determine which auth method to use based on config
   */
  private resolveAuthMethod(): 'certificate' | 'password' {
    const method = this.config.authMethod;

    if (method === 'password') {
      if (!this.config.sapUsername || !this.config.sapPassword) {
        throw new AuthenticationError('Password auth requested but SAP_USERNAME or SAP_PASSWORD not set');
      }
      return 'password';
    }

    if (method === 'certificate') {
      if (!this.config.pfxPath || !this.config.pfxPassphrase) {
        throw new AuthenticationError('Certificate auth requested but PFX_PATH or PFX_PASSPHRASE not set');
      }
      return 'certificate';
    }

    // Auto mode: prefer password if credentials available, fall back to certificate
    if (this.config.sapUsername && this.config.sapPassword) {
      logger.warn('Auto auth: using username/password authentication');
      return 'password';
    }

    if (this.config.pfxPath && this.config.pfxPassphrase) {
      logger.warn('Auto auth: using certificate authentication');
      return 'certificate';
    }

    throw new AuthenticationError(
      'No authentication credentials configured. Set either SAP_USERNAME + SAP_PASSWORD or PFX_PATH + PFX_PASSPHRASE'
    );
  }

  /**
   * Check if a specific browser is available
   */
  private static async checkBrowserAvailable(browserType: string = 'chromium'): Promise<boolean> {
    try {
      const browsers = { chromium, firefox, webkit };
      const browser = browsers[browserType as keyof typeof browsers];
      if (!browser) {
        logger.error(`Browser type '${browserType}' not found in Playwright`);
        return false;
      }

      logger.warn(`Checking ${browserType} browser availability...`);
      const executablePath = await browser.executablePath();

      const fs = await import('fs');
      if (!fs.existsSync(executablePath)) {
        logger.error(`Browser executable not found at: ${executablePath}`);
        return false;
      }

      logger.warn(`Browser executable verified at: ${executablePath}`);
      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      logger.error(`Browser availability check failed for ${browserType}: ${errorMessage}`);
      return false;
    }
  }

  /**
   * Get the appropriate browser launcher
   */
  private getBrowserLauncher() {
    const browserType = process.env.PLAYWRIGHT_BROWSER_TYPE || 'chromium';
    const browsers = { chromium, firefox, webkit };
    const browser = browsers[browserType as keyof typeof browsers];

    if (!browser) {
      throw new BrowserNotFoundError(browserType);
    }

    return browser;
  }

  /**
   * Prepare client certificate configuration for certificate auth
   */
  private prepareClientCertificate() {
    const origin = 'https://accounts.sap.com';

    try {
      if (!existsSync(this.config.pfxPath)) {
        throw new Error(`PFX file not found: ${this.config.pfxPath}`);
      }

      const pfxData = readFileSync(this.config.pfxPath);
      logger.warn(`Loaded PFX certificate from: ${this.config.pfxPath}`);

      return {
        origin,
        pfx: pfxData,
        passphrase: this.config.pfxPassphrase
      };
    } catch (error) {
      throw new CertificateLoadError(this.config.pfxPath, error as Error);
    }
  }

  /**
   * Check if we're still on an authentication page (login, SAML, 2FA)
   * Inspired by PR #4's broader detection and wdi5's auth state tracking
   */
  private isOnAuthPage(url: string, title: string): boolean {
    const urlLower = url.toLowerCase();
    const titleLower = title.toLowerCase();

    return (
      urlLower.includes('accounts.sap.com') ||
      urlLower.includes('login') ||
      urlLower.includes('auth') ||
      urlLower.includes('saml2/idp') ||
      urlLower.includes('two-factor') ||
      titleLower.includes('login') ||
      titleLower.includes('sign in') ||
      titleLower.includes('two-factor') ||
      titleLower.includes('authentication') ||
      titleLower.includes('verify')
    );
  }

  /**
   * Wait for authentication to complete (redirect away from auth pages)
   * Supports MFA/2FA by waiting up to the configured timeout
   */
  private async waitForAuthComplete(page: Page, timeoutMs: number): Promise<void> {
    logger.warn(`Waiting up to ${timeoutMs / 1000}s for authentication to complete...`);

    try {
      await page.waitForURL(
        url => {
          const urlStr = url.toString().toLowerCase();
          return (
            !urlStr.includes('accounts.sap.com') &&
            !urlStr.includes('saml2/idp') &&
            !urlStr.includes('login') &&
            !urlStr.includes('two-factor')
          );
        },
        { timeout: timeoutMs }
      );
      logger.warn('Authentication redirect completed');
    } catch (error) {
      logger.warn('Auth redirect wait timed out, checking current state...');
      // Don't throw - the page might still have valid cookies even if URL detection failed
    }
  }

  /**
   * Perform username/password authentication via form filling
   * Inspired by wdi5's BTPAuthenticator and CustomAuthenticator patterns
   */
  private async authenticateWithPassword(page: Page): Promise<void> {
    const username = this.config.sapUsername!;
    const password = this.config.sapPassword!;

    logger.warn('Starting username/password authentication...');

    // Navigate to SAP
    const authUrl = 'https://me.sap.com/home';
    await page.goto(authUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

    // Wait for network to settle
    try {
      await page.waitForLoadState('networkidle', { timeout: 15000 });
    } catch {
      logger.warn('Network did not settle in 15s, continuing...');
    }

    // Check if we're on the login page
    const currentUrl = page.url();
    const pageTitle = await page.title();

    if (!this.isOnAuthPage(currentUrl, pageTitle)) {
      logger.warn('Already authenticated (not on login page)');
      return;
    }

    logger.warn('On authentication page, filling credentials...');

    // SAP IAS login form handling
    // The login flow can be single-page or multi-step (username first, then password)
    // Similar to wdi5's BTPAuthenticator two-step detection
    try {
      // Step 1: Try to find and fill username field
      // SAP IAS uses various selectors depending on the version
      const usernameSelectors = [
        '#j_username',
        'input[name="j_username"]',
        'input[name="username"]',
        'input[name="email"]',
        'input[type="email"]',
        '#logOnFormUsername',
        'input[name="logOnFormUsername"]',
        '#USERNAME_FIELD input',
        'input[id*="username" i]',
        'input[id*="email" i]'
      ];

      let usernameField = null;
      for (const selector of usernameSelectors) {
        try {
          usernameField = await page.waitForSelector(selector, { timeout: 5000, state: 'visible' });
          if (usernameField) {
            logger.warn(`Found username field: ${selector}`);
            break;
          }
        } catch {
          continue;
        }
      }

      if (!usernameField) {
        // Take screenshot for debugging
        if (this.config.headful) {
          try {
            await page.screenshot({ path: 'debug-login-page.png', fullPage: true });
            logger.warn('Screenshot saved as debug-login-page.png');
          } catch {}
        }
        throw new AuthenticationError('Could not find username field on SAP login page');
      }

      // Clear and fill username
      await usernameField.click({ clickCount: 3 }); // Select all
      await usernameField.fill(username);
      logger.warn('Username entered');

      // Check if password field is already visible (single-page form)
      const passwordSelectors = [
        '#j_password',
        'input[name="j_password"]',
        'input[name="password"]',
        'input[type="password"]',
        '#logOnFormPassword',
        'input[name="logOnFormPassword"]',
        '#PASSWORD_FIELD input',
        'input[id*="password" i]'
      ];

      let passwordField = null;
      for (const selector of passwordSelectors) {
        try {
          passwordField = await page.waitForSelector(selector, { timeout: 2000, state: 'visible' });
          if (passwordField) {
            logger.warn(`Found password field immediately: ${selector}`);
            break;
          }
        } catch {
          continue;
        }
      }

      if (!passwordField) {
        // Multi-step login: submit username first, then wait for password field
        logger.warn('Password field not visible yet, submitting username first (multi-step login)...');

        // Click continue/next button
        const continueSelectors = [
          'button[type="submit"]',
          'input[type="submit"]',
          '#logOnFormSubmit',
          'button[id*="continue" i]',
          'button[id*="next" i]',
          'a[id*="continue" i]'
        ];

        for (const selector of continueSelectors) {
          try {
            const btn = await page.waitForSelector(selector, { timeout: 3000, state: 'visible' });
            if (btn) {
              await btn.click();
              logger.warn(`Clicked continue button: ${selector}`);
              break;
            }
          } catch {
            continue;
          }
        }

        // Wait for password field to appear
        await page.waitForTimeout(2000);

        for (const selector of passwordSelectors) {
          try {
            passwordField = await page.waitForSelector(selector, { timeout: 10000, state: 'visible' });
            if (passwordField) {
              logger.warn(`Found password field after username step: ${selector}`);
              break;
            }
          } catch {
            continue;
          }
        }

        if (!passwordField) {
          throw new AuthenticationError('Could not find password field after username submission');
        }
      }

      // Fill password
      await passwordField.click({ clickCount: 3 });
      await passwordField.fill(password);
      logger.warn('Password entered');

      // Submit the login form
      const submitSelectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        '#logOnFormSubmit',
        'button[id*="login" i]',
        'button[id*="signin" i]',
        'button[id*="submit" i]'
      ];

      for (const selector of submitSelectors) {
        try {
          const btn = await page.waitForSelector(selector, { timeout: 3000, state: 'visible' });
          if (btn) {
            await btn.click();
            logger.warn(`Clicked submit button: ${selector}`);
            break;
          }
        } catch {
          continue;
        }
      }

      // Wait for MFA/2FA or redirect
      // Using configurable timeout (default 120s) to allow manual 2FA entry
      const mfaTimeout = this.config.mfaTimeout;

      // Brief wait for page transition
      await page.waitForTimeout(3000);

      // Check if we're on a 2FA page
      const postLoginUrl = page.url();
      const postLoginTitle = await page.title();

      if (this.isOnAuthPage(postLoginUrl, postLoginTitle)) {
        // Check specifically for 2FA indicators
        const is2FA = postLoginUrl.includes('two-factor') ||
                     postLoginTitle.toLowerCase().includes('two-factor') ||
                     postLoginTitle.toLowerCase().includes('verify') ||
                     postLoginTitle.toLowerCase().includes('passcode') ||
                     postLoginTitle.toLowerCase().includes('totp');

        if (is2FA) {
          logger.warn(`MFA/2FA detected! Please complete 2FA in the browser window (timeout: ${mfaTimeout / 1000}s)`);
          logger.warn('If running headless, set HEADFUL=true to see the browser window for 2FA entry');
        } else {
          logger.warn('Still on auth page after login, waiting for redirect...');
        }

        await this.waitForAuthComplete(page, mfaTimeout);
      }

      logger.warn('Username/password authentication flow completed');

    } catch (error) {
      if (error instanceof AuthenticationError) throw error;
      throw new AuthenticationError(
        `Username/password authentication failed: ${error instanceof Error ? error.message : String(error)}`,
        error as Error
      );
    }
  }

  /**
   * Perform certificate-based authentication
   */
  private async authenticateWithCertificate(page: Page): Promise<void> {
    logger.warn('Starting certificate authentication...');

    const authUrl = 'https://me.sap.com/home';
    const timeout = 30000;

    const navigationPromise = page.goto(authUrl, {
      waitUntil: 'domcontentloaded',
      timeout
    });

    const timeoutPromise = new Promise<never>((_, reject) => {
      setTimeout(() => reject(new AuthenticationTimeoutError(timeout)), timeout);
    });

    await Promise.race([navigationPromise, timeoutPromise]);

    // Wait for network to settle
    try {
      await page.waitForLoadState('networkidle', { timeout: 10000 });
    } catch {
      logger.warn('Network did not settle within 10s, continuing');
    }

    // Check if we need to wait for auth redirect
    const currentUrl = page.url();
    const pageTitle = await page.title();
    logger.warn(`Current page: ${pageTitle} at ${currentUrl}`);

    if (this.isOnAuthPage(currentUrl, pageTitle)) {
      logger.warn('Still on auth page, waiting for certificate auth redirect...');
      // Use MFA timeout to support 2FA even with certificate auth (as per PR #4)
      await this.waitForAuthComplete(page, this.config.mfaTimeout);
    }

    logger.warn('Certificate authentication completed');
  }

  /**
   * Perform the full authentication flow
   */
  private async authenticate(): Promise<void> {
    // First try to load cached token
    const cachedToken = this.loadCachedToken();
    if (cachedToken && this.isTokenValidFromCache(cachedToken)) {
      logger.warn('Using cached SAP authentication token');
      this.authState = {
        token: cachedToken.access_token,
        expiresAt: cachedToken.expiresAt,
        isAuthenticated: true
      };
      return;
    }

    const authMethod = this.resolveAuthMethod();
    logger.warn(`Starting SAP authentication flow (method: ${authMethod})...`);

    const startTime = Date.now();

    try {
      const browserLauncher = this.getBrowserLauncher();
      const browserType = process.env.PLAYWRIGHT_BROWSER_TYPE || 'chromium';

      if (!(await SapAuthenticator.checkBrowserAvailable(browserType))) {
        throw new BrowserNotFoundError(browserType);
      }

      // Launch browser
      const headless = process.env.HEADFUL !== 'true';
      const launchOptions = { headless, ignoreHTTPSErrors: true };

      logger.warn(`Launching browser (headless: ${headless})`);

      const maxRetries = 3;
      let lastError: Error | null = null;

      for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
          this.browser = await browserLauncher.launch(launchOptions);
          logger.warn(`Browser launched (attempt ${attempt}/${maxRetries})`);
          break;
        } catch (error) {
          lastError = error as Error;
          const errorMsg = error instanceof Error ? error.message : String(error);
          logger.error(`Browser launch failed (attempt ${attempt}/${maxRetries}): ${errorMsg}`);

          if (errorMsg.includes('pthread_create') || errorMsg.includes('Resource temporarily unavailable')) {
            if (attempt < maxRetries) {
              const delayMs = Math.pow(2, attempt) * 1000;
              logger.warn(`Resource exhaustion, retrying in ${delayMs / 1000}s...`);
              await new Promise(resolve => setTimeout(resolve, delayMs));
              continue;
            }
          }

          if (attempt >= maxRetries) throw error;
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      }

      if (!this.browser) {
        throw new Error(`Failed to launch browser after ${maxRetries} attempts: ${lastError?.message || 'Unknown error'}`);
      }

      // Create browser context
      const contextOptions: any = {
        ignoreHTTPSErrors: true,
        locale: 'en-US',
        viewport: { width: 1280, height: 720 }
      };

      // Add client certificate only for certificate auth
      if (authMethod === 'certificate') {
        const clientCertificate = this.prepareClientCertificate();
        contextOptions.clientCertificates = [clientCertificate];
      }

      this.context = await this.browser.newContext(contextOptions);
      this.page = await this.context.newPage();

      // Add debug event listeners
      this.page.on('dialog', dialog => {
        logger.warn(`Dialog appeared: ${dialog.type()} ${dialog.message()}`);
        dialog.dismiss().catch(() => {});
      });

      // Perform authentication based on method
      if (authMethod === 'password') {
        await this.authenticateWithPassword(this.page);
      } else {
        await this.authenticateWithCertificate(this.page);
      }

      // Wait a moment for cookies to be fully set
      await this.page.waitForTimeout(3000);

      // Extract cookies
      logger.warn('Extracting authentication cookies...');
      const allCookies = await this.context.cookies();
      logger.warn(`Retrieved ${allCookies.length} cookies`);

      const cookieString = allCookies.map(cookie =>
        `${cookie.name}=${cookie.value}`
      ).join('; ');

      const expiresAt = Date.now() + (this.config.maxJwtAgeH * 60 * 60 * 1000);

      this.authState = {
        token: cookieString,
        expiresAt,
        isAuthenticated: true
      };

      this.saveCachedToken({
        access_token: cookieString,
        cookies: allCookies,
        expiresAt
      });

      const duration = Date.now() - startTime;
      logger.warn(`SAP authentication completed in ${duration}ms (method: ${authMethod})`);

    } catch (error) {
      logger.error('Authentication failed:', error);
      this.authState = { isAuthenticated: false };

      if (error instanceof AuthenticationTimeoutError ||
          error instanceof CertificateLoadError ||
          error instanceof BrowserNotFoundError ||
          error instanceof AuthenticationError) {
        throw error;
      } else {
        throw new AuthenticationError('Authentication process failed', error as Error);
      }
    } finally {
      await this.cleanup();
    }
  }

  /**
   * Clean up browser resources
   */
  private async cleanup(): Promise<void> {
    if (this.browser) {
      try {
        await this.browser.close();
        logger.warn('Browser session closed');
      } catch (closeError) {
        logger.error('Error closing browser:', closeError);
      } finally {
        this.browser = null;
        this.context = null;
        this.page = null;
      }
    }
  }

  /**
   * Load cached token from disk
   */
  private loadCachedToken(): any {
    try {
      if (existsSync(TOKEN_CACHE_FILE)) {
        const cached = JSON.parse(readFileSync(TOKEN_CACHE_FILE, 'utf-8'));
        return cached;
      }
    } catch (error) {
      logger.warn('Failed to load cached token:', error);
    }
    return null;
  }

  /**
   * Check if cached token is still valid
   */
  private isTokenValidFromCache(cachedToken: any): boolean {
    if (!cachedToken.access_token || !cachedToken.expiresAt) {
      return false;
    }

    const bufferMs = 5 * 60 * 1000;
    return Date.now() < (cachedToken.expiresAt - bufferMs);
  }

  /**
   * Save token to disk cache
   */
  private saveCachedToken(tokenData: any): void {
    try {
      writeFileSync(TOKEN_CACHE_FILE, JSON.stringify(tokenData, null, 2));
      logger.warn('Token cached for future use');
    } catch (error) {
      logger.warn('Failed to cache token:', error);
    }
  }

  /**
   * Force cleanup and reset authentication state
   */
  async destroy(): Promise<void> {
    this.authState = { isAuthenticated: false };
    await this.cleanup();
  }
}
