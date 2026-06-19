#!/usr/bin/env node
// Stdio MCP proxy for the GetTreatmentHelp remote MCP server.
// Packaged so Glama can build, run, and introspect a containerized release of
// a server whose real implementation is a remote Cloudflare Pages Function.
//
// Design:
//   initialize  -> standard MCP handshake via the SDK
//   tools/list  -> returns an embedded static snapshot (tools.json) captured
//                  from the live endpoint; requires ZERO network so the build
//                  test and Tool Definition Quality scan always read real schemas
//   tools/call  -> forwards the JSON-RPC call to UPSTREAM_URL over HTTP and
//                  returns the upstream result; graceful error if unreachable
//
// The ~8MB facilities.json data layer and Cloudflare bindings never enter this
// container; the proxy reaches the live data only at call time.

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  ListToolsRequestSchema,
  CallToolRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { readFileSync } from "node:fs";

const UPSTREAM_URL =
  process.env.UPSTREAM_URL || "https://gth-mcp-server.pages.dev/mcp";
const SERVER_NAME = process.env.SERVER_NAME || "gettreatmenthelp";
const SERVER_VERSION = "1.0.0";

// Embedded static tool snapshot (source of truth: live tools/list).
const TOOLS = JSON.parse(
  readFileSync(new URL("./tools.json", import.meta.url), "utf-8")
);

let rpcId = 0;

// Parse an upstream response that may be plain JSON or a Streamable-HTTP SSE
// frame ("data: {...}"). Returns the parsed JSON-RPC envelope.
function parseEnvelope(text) {
  try {
    return JSON.parse(text);
  } catch (_) {
    // fall through to SSE handling
  }
  const lines = text.split(/\r?\n/);
  for (const line of lines) {
    const m = line.match(/^data:\s*(.*)$/);
    if (m && m[1]) {
      try {
        return JSON.parse(m[1]);
      } catch (_) {
        // keep scanning
      }
    }
  }
  throw new Error("Unparseable upstream response: " + text.slice(0, 200));
}

async function callUpstream(name, args) {
  let res;
  try {
    res = await fetch(UPSTREAM_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: ++rpcId,
        method: "tools/call",
        params: { name: name, arguments: args || {} },
      }),
    });
  } catch (err) {
    throw new Error("Upstream unreachable (" + UPSTREAM_URL + "): " + err.message);
  }
  const body = await res.text();
  if (!res.ok) {
    throw new Error("Upstream HTTP " + res.status + ": " + body.slice(0, 200));
  }
  const envelope = parseEnvelope(body);
  if (envelope.error) {
    const e = envelope.error;
    throw new Error("Upstream error: " + (e.message || JSON.stringify(e)));
  }
  return envelope.result;
}

const server = new Server(
  { name: SERVER_NAME, version: SERVER_VERSION },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return { tools: TOOLS };
});

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  const result = await callUpstream(name, args);
  if (result && Array.isArray(result.content)) {
    return result;
  }
  // Defensive wrap if upstream ever returns a non-standard shape.
  return {
    content: [
      {
        type: "text",
        text: typeof result === "string" ? result : JSON.stringify(result),
      },
    ],
  };
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
}

main().catch((err) => {
  process.stderr.write("Fatal: " + (err && err.stack ? err.stack : err) + "\n");
  process.exit(1);
});
