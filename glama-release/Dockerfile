# Containerized Glama release for the GetTreatmentHelp MCP server.
# Thin stdio proxy to the live remote endpoint; the ~8MB facilities.json data
# layer is NOT copied into the image -- the proxy reaches data at call time.
#
# BUILD CONTEXT = repository root.
#   docker build -f glama-release/Dockerfile -t gth-mcp-proxy .
# COPY paths are repo-root-relative so this Dockerfile lives in a subdir while
# the build context stays at the repo root (Glama's default).
FROM node:20-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY glama-release/package.json ./
RUN npm install --omit=dev

# Application + embedded tool snapshot.
COPY glama-release/entrypoint.mjs ./
COPY glama-release/tools.json ./

CMD ["node", "entrypoint.mjs"]
