# Containerized Glama release for the GetTreatmentHelp MCP server.
# Thin stdio proxy to the live remote endpoint; the ~8MB facilities.json data
# layer is NOT copied into the image -- the proxy reaches data at call time.
FROM node:20-slim

WORKDIR /app

# Install dependencies first for layer caching.
COPY package.json ./
RUN npm install --omit=dev

# Application + embedded tool snapshot.
COPY entrypoint.mjs ./
COPY tools.json ./

CMD ["node", "entrypoint.mjs"]
