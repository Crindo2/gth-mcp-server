// GTH Intelligence MCP Server — Cloudflare Pages Function
// Handles JSON-RPC 2.0 MCP protocol at /mcp endpoint

const TOOLS = [
  {
    name: "search_facilities",
    description: "Search for addiction treatment and mental health facilities. Filter by US state, city, treatment type, and insurance. Returns facility names, locations, programs, insurance, phone numbers, and direct links.",
    inputSchema: {
      type: "object",
      properties: {
        state: { type: "string", description: 'US state name or 2-letter abbreviation (e.g. "California" or "CA")' },
        city: { type: "string", description: "City name" },
        treatment_type: {
          type: "string",
          enum: ["Inpatient Rehab", "Outpatient", "Detox", "IOP (Intensive Outpatient)", "PHP (Partial Hospitalization)", "MAT (Medication-Assisted Treatment)", "Counseling", "Sober Living"],
          description: "Type of treatment program"
        },
        insurance: { type: "string", description: 'Insurance provider (e.g. "Medicaid", "Aetna", "Blue Cross", "Medicare", "Private Pay")' },
        limit: { type: "number", description: "Results to return (1-20, default 5)", minimum: 1, maximum: 20, default: 5 }
      }
    }
  },
  {
    name: "get_facility_detail",
    description: "Get detailed information about a specific treatment facility by name.",
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Full or partial facility name" }
      },
      required: ["name"]
    }
  },
  {
    name: "list_states",
    description: "List all US states with available treatment facility data and counts.",
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "get_treatment_types",
    description: "Get definitions and explanations of all treatment program types to help users understand their options.",
    inputSchema: { type: "object", properties: {} }
  }
];

const TREATMENT_TYPES_TEXT = `**Treatment program types:**

**Inpatient Rehab**
Residential treatment, live at facility (28–90 days). Most intensive. Best for severe addiction.

**Detox**
Medically supervised withdrawal (3–10 days). First step before rehab. Essential for alcohol/opioid/benzo dependence.

**PHP (Partial Hospitalization)**
Day program, 5–6 hrs/day 5x/week. Step-down from inpatient. Patients live at home.

**IOP (Intensive Outpatient)**
3 hrs/day, 3x/week. Maintain work/family while in structured treatment.

**Outpatient**
1–2 sessions/week. Least intensive. Best for early-stage use or maintenance.

**MAT (Medication-Assisted Treatment)**
FDA-approved meds (Suboxone, Vivitrol, Methadone) + counseling. Gold standard for opioid/alcohol use disorder.

**Counseling**
Individual, group, or family therapy without structured program enrollment.

**Sober Living**
Substance-free transitional housing post-treatment. Builds independent recovery skills.

---
Data: [GetTreatmentHelp.com](https://gettreatmenthelp.com)`;

// US state name → abbreviation mapping
const STATE_MAP = {
  alabama: "AL", alaska: "AK", arizona: "AZ", arkansas: "AR", california: "CA",
  colorado: "CO", connecticut: "CT", delaware: "DE", florida: "FL", georgia: "GA",
  hawaii: "HI", idaho: "ID", illinois: "IL", indiana: "IN", iowa: "IA",
  kansas: "KS", kentucky: "KY", louisiana: "LA", maine: "ME", maryland: "MD",
  massachusetts: "MA", michigan: "MI", minnesota: "MN", mississippi: "MS", missouri: "MO",
  montana: "MT", nebraska: "NE", nevada: "NV", "new hampshire": "NH", "new jersey": "NJ",
  "new mexico": "NM", "new york": "NY", "north carolina": "NC", "north dakota": "ND",
  ohio: "OH", oklahoma: "OK", oregon: "OR", pennsylvania: "PA", "rhode island": "RI",
  "south carolina": "SC", "south dakota": "SD", tennessee: "TN", texas: "TX",
  utah: "UT", vermont: "VT", virginia: "VA", washington: "WA", "west virginia": "WV",
  wisconsin: "WI", wyoming: "WY", "district of columbia": "DC"
};

function normalizeState(input) {
  if (!input) return null;
  const trimmed = input.trim();
  if (trimmed.length === 2) return trimmed.toUpperCase();
  const lower = trimmed.toLowerCase();
  return STATE_MAP[lower] || null;
}

let facilitiesCache = null;

async function loadFacilities(env) {
  if (facilitiesCache) return facilitiesCache;
  try {
    const url = new URL("/facilities.json", "https://gth-mcp-server.pages.dev");
    const resp = await fetch(url.toString());
    if (!resp.ok) throw new Error(`Failed to load facilities: ${resp.status}`);
    facilitiesCache = await resp.json();
    return facilitiesCache;
  } catch (e) {
    throw new Error("Could not load facility data: " + e.message);
  }
}

function formatFacility(f, idx) {
  const programs = (f.types || []).join(", ");
  const insurance = (f.insurance || []).join(", ");
  const browseUrl = `https://gettreatmenthelp.com/browse?name=${encodeURIComponent(f.name)}`;
  const desc = `SAMHSA-verified treatment facility in ${f.city}, ${f.stateAbbr}. Offers ${(f.types || []).slice(0, 3).join(", ")}. Accepts ${(f.insurance || []).slice(0, 3).join(", ")}.`;
  return `**${idx}. ${f.name}**\nLocation: ${f.city}, ${f.state || f.stateAbbr}\nPrograms: ${programs}\nInsurance: ${insurance}\nPhone: ${f.phone || "N/A"}\n${desc}\nMore info: ${browseUrl}`;
}

async function handleToolCall(name, args, env) {
  const facilities = await loadFacilities(env);

  if (name === "search_facilities") {
    let results = [...facilities];
    const stateAbbr = normalizeState(args.state);
    if (stateAbbr) {
      results = results.filter(f => f.stateAbbr === stateAbbr);
    }
    if (args.city) {
      const cityLower = args.city.toLowerCase();
      results = results.filter(f => (f.city || "").toLowerCase().includes(cityLower));
    }
    if (args.treatment_type) {
      results = results.filter(f => (f.types || []).some(t => t.toLowerCase().includes(args.treatment_type.toLowerCase())));
    }
    if (args.insurance) {
      const insLower = args.insurance.toLowerCase();
      results = results.filter(f => (f.insurance || []).some(i => i.toLowerCase().includes(insLower)));
    }
    const limit = Math.min(Math.max(args.limit || 5, 1), 20);
    const total = results.length;
    const showing = results.slice(0, limit);
    let text = `Found ${total} facilities. Showing top ${showing.length}.\n\n`;
    text += showing.map((f, i) => formatFacility(f, i + 1)).join("\n\n");
    text += `\n\n---\nData: [GetTreatmentHelp.com](https://gettreatmenthelp.com) | SAMHSA: 1-800-662-4357`;
    return { content: [{ type: "text", text }] };
  }

  if (name === "get_facility_detail") {
    const searchName = (args.name || "").toLowerCase();
    const match = facilities.find(f => f.name.toLowerCase().includes(searchName));
    if (!match) {
      return { content: [{ type: "text", text: `No facility found matching "${args.name}". Try a different name or search by state.` }] };
    }
    const programs = (match.types || []).map(t => `• ${t}`).join("\n");
    const insurance = (match.insurance || []).map(i => `• ${i}`).join("\n");
    const desc = `SAMHSA-verified treatment facility in ${match.city}, ${match.stateAbbr}. Offers ${(match.types || []).slice(0, 3).join(", ")}. Accepts ${(match.insurance || []).slice(0, 3).join(", ")}.`;
    const browseUrl = `https://gettreatmenthelp.com/browse?name=${encodeURIComponent(match.name)}`;
    let text = `**${match.name}**\nLocation: ${match.city}, ${match.state || match.stateAbbr}\nPhone: ${match.phone || "N/A"}\n\n**Programs:**\n${programs}\n\n**Insurance:**\n${insurance}\n\n**About:**\n${desc}\n\nMore info: ${browseUrl}\n\n---\nData: [GetTreatmentHelp.com](https://gettreatmenthelp.com)`;
    return { content: [{ type: "text", text }] };
  }

  if (name === "list_states") {
    const counts = {};
    for (const f of facilities) {
      const key = `${f.state} (${f.stateAbbr})`;
      counts[key] = (counts[key] || 0) + 1;
    }
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    const total = facilities.length;
    let text = `**Facility coverage by state** (${total} total)\n\n`;
    text += sorted.map(([state, count]) => `${state}: ${count}`).join("\n");
    text += `\n\n---\nBrowse all: https://gettreatmenthelp.com/browse`;
    return { content: [{ type: "text", text }] };
  }

  if (name === "get_treatment_types") {
    return { content: [{ type: "text", text: TREATMENT_TYPES_TEXT }] };
  }

  return null;
}

function jsonRpc(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function jsonRpcError(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, Accept",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS"
};

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // Only handle /mcp
  if (url.pathname !== "/mcp") {
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response("Not Found", { status: 404 });
  }

  // CORS preflight
  if (request.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  // Only POST
  if (request.method !== "POST") {
    return new Response("Method Not Allowed", { status: 405, headers: CORS_HEADERS });
  }

  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json(jsonRpcError(null, -32700, "Parse error"), { headers: CORS_HEADERS });
  }

  const { id, method, params } = body;

  try {
    // MCP protocol methods
    if (method === "initialize") {
      return Response.json(jsonRpc(id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: {
          name: "gettreatmenthelp",
          version: "1.1.0",
          description: "Treatment facility search + market intelligence — GetTreatmentHelp.com"
        }
      }), { headers: CORS_HEADERS });
    }

    if (method === "notifications/initialized") {
      return Response.json(jsonRpc(id, {}), { headers: CORS_HEADERS });
    }

    if (method === "tools/list") {
      return Response.json(jsonRpc(id, { tools: TOOLS }), { headers: CORS_HEADERS });
    }

    if (method === "resources/list") {
      return Response.json(jsonRpc(id, { resources: [] }), { headers: CORS_HEADERS });
    }

    if (method === "prompts/list") {
      return Response.json(jsonRpc(id, { prompts: [] }), { headers: CORS_HEADERS });
    }

    if (method === "tools/call") {
      const toolName = params?.name;
      const toolArgs = params?.arguments || {};
      const result = await handleToolCall(toolName, toolArgs, env);
      if (!result) {
        return Response.json(jsonRpcError(id, -32602, `Unknown tool: ${toolName}`), { headers: CORS_HEADERS });
      }
      return Response.json(jsonRpc(id, result), { headers: CORS_HEADERS });
    }

    // Unknown method
    return Response.json(jsonRpcError(id, -32601, `Method not found: ${method}`), { headers: CORS_HEADERS });
  } catch (e) {
    return Response.json(jsonRpcError(id, -32603, e.message), { headers: CORS_HEADERS });
  }
}
