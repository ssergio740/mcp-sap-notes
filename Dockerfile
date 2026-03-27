# Use official Playwright image - includes chromium and all system deps
FROM mcr.microsoft.com/playwright:v1.52.0-noble

WORKDIR /app

# Copy package files first for better layer caching
COPY package.json package-lock.json ./

# Install dependencies
RUN npm ci --no-audit --no-fund

# Copy source and build
COPY tsconfig.json ./
COPY src/ ./src/

RUN npm run build

# Install only chromium (image may have different version than what we need)
RUN npx playwright install chromium

# Default environment
ENV DOCKER_ENV=true \
    NODE_ENV=production \
    HTTP_PORT=3123 \
    AUTO_START=true \
    LOG_LEVEL=info \
    MAX_JWT_AGE_H=12 \
    MFA_TIMEOUT=120000

EXPOSE 3123

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://localhost:3123/health').then(r => r.ok ? process.exit(0) : process.exit(1)).catch(() => process.exit(1))"

CMD ["node", "dist/http-mcp-server.js"]
