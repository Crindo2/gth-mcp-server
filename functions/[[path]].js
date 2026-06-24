// GTH Intelligence MCP Server — Cloudflare Pages Function
// Handles JSON-RPC 2.0 MCP protocol at /mcp endpoint

const AT_BASE = 'appvHqDMSu6aCwNxA';
const AT_LOG_TABLE = 'tblAZCSjdaJLbGh0L'; // "GTH MCP Query Log"

const TOOLS = [
  {
    name: "search_facilities",
    title: "Search Treatment Facilities",
    description: "Search the 12,338 curated, SAMHSA-sourced US addiction treatment facility directory by state, city, treatment type, and insurance. Returns matched facilities with name, city/state, programs offered, insurance accepted, phone, and browse URL. Use this to find candidates — then call get_facility_detail for one facility's full profile. If the user is uncertain about location coverage, call list_states first.",
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    inputSchema: {
      type: "object",
      properties: {
        state: { type: "string", description: 'US state name or 2-letter abbreviation (e.g. "California" or "CA"). Required — searches are scoped to one state at a time.' },
        city: { type: "string", description: "City name (partial match supported — 'san fran' matches 'San Francisco')" },
        treatment_type: {
          type: "string",
          enum: ["Inpatient Rehab", "Outpatient", "Detox", "IOP (Intensive Outpatient)", "PHP (Partial Hospitalization)", "MAT (Medication-Assisted Treatment)", "Counseling", "Sober Living"],
          description: "Type of treatment program. Call get_treatment_types if the user is unsure which applies."
        },
        insurance: { type: "string", description: 'Insurance provider accepted (e.g. "Medicaid", "Aetna", "Blue Cross", "Medicare", "Private Pay"). Partial match supported.' },
        limit: { type: "number", description: "Max results to return (1-20, default 5)", minimum: 1, maximum: 20, default: 5 }
      },
      required: ["state"]
    }
  },
  {
    name: "get_facility_detail",
    title: "Get Facility Detail",
    description: "Get the full profile of one specific treatment facility: address, phone, programs offered, insurance plans accepted, SAMHSA verification status, and a direct browse URL. Supports partial name matching — returns the best match if multiple facilities contain the query string. Use after search_facilities when the user wants to drill into a named facility.",
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    inputSchema: {
      type: "object",
      properties: {
        name: { type: "string", description: "Full or partial facility name (e.g. 'Betty Ford' or 'Hazelden Betty Ford Center')" }
      },
      required: ["name"]
    }
  },
  {
    name: "list_states",
    title: "List States with Coverage",
    description: "List every US state that has treatment facility data in this directory, with per-state facility counts. Returns an array of {state, stateAbbr, count}. Use as a first step when the user's location is unclear, or to discover where coverage exists before calling search_facilities.",
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    inputSchema: { type: "object", properties: {} }
  },
  {
    name: "get_treatment_types",
    title: "Get Treatment Type Definitions",
    description: "Get definitions of all treatment program types (Inpatient Rehab, Detox, PHP, IOP, Outpatient, MAT, Counseling, Sober Living) with duration, intensity, and typical fit. Returns markdown-formatted explanations. Use when the user is uncertain which treatment_type to pass to search_facilities, or asks 'what's the difference between X and Y'.",
    annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
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
  const desc = `Treatment facility in ${f.city}, ${f.stateAbbr}. Offers ${(f.types || []).slice(0, 3).join(", ")}. Accepts ${(f.insurance || []).slice(0, 3).join(", ")}.`;
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
    return { content: [{ type: "text", text }], _resultsCount: total };
  }

  if (name === "get_facility_detail") {
    const searchName = (args.name || "").toLowerCase();
    const match = facilities.find(f => f.name.toLowerCase().includes(searchName));
    if (!match) {
      return { content: [{ type: "text", text: `No facility found matching "${args.name}". Try a different name or search by state.` }], _resultsCount: 0 };
    }
    const programs = (match.types || []).map(t => `• ${t}`).join("\n");
    const insurance = (match.insurance || []).map(i => `• ${i}`).join("\n");
    const desc = `Treatment facility in ${match.city}, ${match.stateAbbr}. Offers ${(match.types || []).slice(0, 3).join(", ")}. Accepts ${(match.insurance || []).slice(0, 3).join(", ")}.`;
    const browseUrl = `https://gettreatmenthelp.com/browse?name=${encodeURIComponent(match.name)}`;
    let text = `**${match.name}**\nLocation: ${match.city}, ${match.state || match.stateAbbr}\nPhone: ${match.phone || "N/A"}\n\n**Programs:**\n${programs}\n\n**Insurance:**\n${insurance}\n\n**About:**\n${desc}\n\nMore info: ${browseUrl}\n\n---\nData: [GetTreatmentHelp.com](https://gettreatmenthelp.com)`;
    return { content: [{ type: "text", text }], _resultsCount: 1 };
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
  "Access-Control-Allow-Headers": "Content-Type, Accept, x-api-key, Mcp-Session-Id, MCP-Protocol-Version",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Expose-Headers": "Mcp-Session-Id"
};

// ── Origin validation (MCP Streamable HTTP security requirement) ──
// Per the MCP spec, servers MUST validate the Origin header on all incoming connections
// to the MCP endpoint to prevent DNS rebinding attacks. Non-browser MCP clients (Claude
// Desktop, mcp-remote, server-to-server) send no Origin and are allowed; browser requests
// must come from an allowed host.
const ALLOWED_ORIGIN_HOSTS = ["gth-mcp-server.pages.dev", "claude.ai", "claude.com", "anthropic.com", "chatgpt.com", "openai.com", "localhost", "127.0.0.1"];

function originAllowed(request) {
  const origin = request.headers.get("Origin");
  if (!origin) return true; // no Origin header = non-browser client; no DNS-rebinding vector
  let hostname;
  try { hostname = new URL(origin).hostname; } catch { return false; }
  return ALLOWED_ORIGIN_HOSTS.some(h => hostname === h || hostname.endsWith("." + h));
}

// ── Access control (2026-06-10): free distribution. Anonymous tools/call ENABLED; paid tiers
//    retired. Rate cap 100 calls/IP/day (rolling daily). Legacy keys honored but NOT required.
//    Higher-volume access -> contact via /api-access/. Supersedes the Apr-2026 key-only posture.
//    EKRA: informational B2B treatment-facility data distribution only — no affiliate,
//    pay-per-lead, or ranked-placement monetization on any GTH surface. ──

const GTH_DAILY_LIMIT = 100;   // free-tier calls per IP per UTC day (rolling daily — no lifetime accumulation)
const GTH_CONTACT_URL = 'https://gettreatmenthelp.com/api-access/';

function gthUtcDay() { return new Date().toISOString().slice(0, 10); }

// Legacy plan limits retained so any pre-existing keyed caller keeps working (keys are not required).
function gthPlanLimits(env) {
  return {
    developer:  { limit: 500,     hardCap: true,  reportUsage: false, meterEvent: null },
    growth:     { limit: 2500,    hardCap: true,  reportUsage: false, meterEvent: null },
    scale:      {
      limit: 10000,
      hardCap: !env?.GTH_SCALE_METER_EVENT,
      reportUsage: !!env?.GTH_SCALE_METER_EVENT,
      meterEvent: env?.GTH_SCALE_METER_EVENT || null,
    },
    enterprise: {
      limit: 50000,
      hardCap: !env?.GTH_ENT_METER_EVENT,
      reportUsage: !!env?.GTH_ENT_METER_EVENT,
      meterEvent: env?.GTH_ENT_METER_EVENT || null,
    },
    payg:       { limit: Infinity, hardCap: false, reportUsage: true, meterEvent: 'gth_api_call' },
  };
}

async function validateKey(request, env) {
  const apiKey = request.headers.get('x-api-key') || '';

  // Legacy keyed access (optional): a recognized, non-canceled key bypasses the anonymous daily cap.
  if (apiKey) {
    const kv = env?.GTH_API_KEYS;
    if (kv) {
      const raw = await kv.get(apiKey);
      if (raw) {
        const record = JSON.parse(raw);
        const planSpec = gthPlanLimits(env)[record.plan];
        if (record.status !== 'canceled' && planSpec) {
          if (planSpec.hardCap && record.callsThisPeriod >= planSpec.limit) {
            return { allowed: false, reason: `Monthly quota reached (${planSpec.limit.toLocaleString()} calls on the ${record.plan} plan). For higher-volume access, get in touch via ${GTH_CONTACT_URL}` };
          }
          return { allowed: true, record, apiKey, planSpec };
        }
      }
    }
    // Unrecognized or canceled key: fall through to the free anonymous tier (never hard-block).
  }

  // Free anonymous tier — 100 calls/IP/day (UTC), rolling daily, no lifetime cap.
  const meter = env?.GTH_CALL_METER;
  if (meter) {
    const ip = request.headers.get('cf-connecting-ip') || 'unknown';
    const dayKey = `ip_daily:${ip}:${gthUtcDay()}`;
    const count = parseInt(await meter.get(dayKey) || '0', 10);
    if (count >= GTH_DAILY_LIMIT) {
      return { allowed: false, reason: `Free tier limit reached (${GTH_DAILY_LIMIT} calls/IP/day; resets 00:00 UTC). For higher-volume access, get in touch via ${GTH_CONTACT_URL}` };
    }
    await meter.put(dayKey, String(count + 1), { expirationTtl: 172800 });
  }
  return { allowed: true, anonymous: true };
}

// ============================================================================
// MCP demand-telemetry enrichment (D561, 2026-06-24) -- CANONICAL block, kept
// IDENTICAL in gph-mcp-server/functions/mcp.js and the scratch canonical copy
// (_scratch/mcp-telemetry-2026-06-24/enrichment-canonical.js). Logic is KV-free and
// network-free: caller_class is UA/Origin-only and deterministic at write time.
// Cadence-based crawler detection lives in the nightly rollup ONLY, and may only
// promote unknown -> known_crawler, never demote organic_assistant.
// ============================================================================

const ASSISTANT_ORIGIN_HOSTS = {
  'chatgpt.com': 'chatgpt', 'openai.com': 'chatgpt', 'oai.com': 'chatgpt',
  'claude.ai': 'claude', 'claude.com': 'claude', 'anthropic.com': 'claude',
  'perplexity.ai': 'perplexity',
  'gemini.google.com': 'gemini',
};

function originHostOf(request) {
  const o = request.headers.get('Origin');
  if (!o) return '';
  try { return new URL(o).hostname.toLowerCase(); } catch { return ''; }
}

function assistantFromOrigin(host) {
  if (!host) return null;
  for (const h in ASSISTANT_ORIGIN_HOSTS) {
    if (host === h || host.endsWith('.' + h)) return ASSISTANT_ORIGIN_HOSTS[h];
  }
  return null;
}

function assistantFromUA(ua) {
  if (!ua) return null;
  if (/chatgpt|openai/i.test(ua)) return 'chatgpt';
  if (/claude|anthropic/i.test(ua)) return 'claude';
  if (/perplexity/i.test(ua)) return 'perplexity';
  if (/\bgemini\b|google-?bard/i.test(ua)) return 'gemini';
  if (/copilot/i.test(ua)) return 'copilot';
  return null;
}

function assistantChannel(ua, originHost) {
  return assistantFromOrigin(originHost) || assistantFromUA(ua);
}

function classifyCaller(ua, originHost) {
  if (assistantFromOrigin(originHost)) return 'organic_assistant';
  const u = (ua || '').trim();
  if (!u) return 'unknown';
  if (/probe|listability|uptime|pingdom|healthcheck|statuscake|\bmonitor\b/i.test(u)) return 'directory_probe';
  if (/^curl|^wget|python-requests|python-httpx|\bhttpx\b|node-fetch|go-http-client|^axios|cbeg-floor-check|postman|insomnia/i.test(u)) return 'self_test';
  if (assistantFromUA(u)) return 'organic_assistant';
  if (/bot\b|spider|crawl|chiark|slurp|bingpreview|facebookexternalhit|quality index|scraper|http-client/i.test(u)) return 'known_crawler';
  return 'unknown';
}

function funnelStep(tool) {
  if (tool === 'get_provider_detail' || tool === 'get_facility_detail') return 'drill';
  if (tool === 'list_states' || tool === 'get_treatment_types') return 'reference';
  return 'discover';
}

function demandCell(server, args) {
  const n = v => ((v == null ? '' : String(v)).trim().toLowerCase()) || '*';
  if (server === 'gth') return [n(args.treatment_type), n(args.state), n(args.city), n(args.insurance)].join('|');
  return [n(args.category), n(args.specialty), n(args.state), n(args.ehr_system)].join('|');
}

function telemetryUtcDay() { return new Date().toISOString().slice(0, 10); }

async function sha256hex(s) {
  const data = new TextEncoder().encode(s);
  const buf = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// Mcp-Session-Id (server-issued at initialize, client-echoed) is the load-bearing
// session key. Fallback for sessionless callers: salted hash of transient ip+ua with a
// daily-rotating salt -- raw ip/ua are NEVER stored as inputs, only the opaque derived
// id is stored. 'm:' = real MCP session, 'd:' = derived fallback.
async function deriveSessionId(request, env) {
  const incoming = request.headers.get('Mcp-Session-Id');
  if (incoming) return 'm:' + (await sha256hex(incoming)).slice(0, 16);
  const ip = request.headers.get('cf-connecting-ip') || '';
  const ua = request.headers.get('user-agent') || '';
  const salt = (env && env.SESSION_SALT ? env.SESSION_SALT : 'cbeg-mcp') + ':' + telemetryUtcDay();
  return 'd:' + (await sha256hex(salt + '|' + ip + '|' + ua)).slice(0, 16);
}

async function buildTelemetry(server, request, env, toolName, args, resultsCount, tier, ids) {
  const ua = request.headers.get('user-agent') || '';
  const originHost = originHostOf(request);
  const step = funnelStep(toolName);
  const rc = (typeof resultsCount === 'number') ? resultsCount : null;
  const zero = (step !== 'reference' && rc === 0) ? 1 : 0;
  const a = args || {};
  return {
    ts: new Date().toISOString(),
    server,
    tool: toolName || '',
    caller_class: classifyCaller(ua, originHost),
    assistant_channel: assistantChannel(ua, originHost),
    source: 'mcp',
    user_agent: ua,
    session_id: await deriveSessionId(request, env),
    funnel_step: step,
    zero_result: zero,
    results_count: rc,
    api_key_tier: tier || 'anonymous',
    category: a.category || null,
    specialty: a.specialty || null,
    city: a.city || null,
    state: a.state || null,
    ehr_system: a.ehr_system || null,
    treatment_type: a.treatment_type || null,
    insurance: a.insurance || null,
    search_term: a.name || null,
    demand_cell: demandCell(server, a),
    vendor_surfaced: (ids && ids.surfaced && ids.surfaced.length) ? JSON.stringify(ids.surfaced) : null,
    vendor_drilled: (ids && ids.drilled) ? ids.drilled : null,
    raw_args: JSON.stringify(a),
  };
}

// Independent, non-blocking D1 sink. Own try/catch; never throws to the caller.
async function writeTelemetryD1(env, rec) {
  const db = env && env.TELEMETRY_DB;
  if (!db) { console.error('writeTelemetryD1: TELEMETRY_DB not bound -- D1 telemetry skipped'); return; }
  try {
    await db.prepare(
      `INSERT INTO mcp_usage_log
        (ts, server, tool, caller_class, assistant_channel, source, user_agent, session_id, funnel_step,
         zero_result, results_count, api_key_tier, category, specialty, city, state, ehr_system,
         treatment_type, insurance, search_term, demand_cell, vendor_surfaced, vendor_drilled, raw_args)
       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`
    ).bind(
      rec.ts, rec.server, rec.tool, rec.caller_class, rec.assistant_channel, rec.source, rec.user_agent,
      rec.session_id, rec.funnel_step, rec.zero_result, rec.results_count, rec.api_key_tier,
      rec.category, rec.specialty, rec.city, rec.state, rec.ehr_system,
      rec.treatment_type, rec.insurance, rec.search_term, rec.demand_cell,
      rec.vendor_surfaced, rec.vendor_drilled, rec.raw_args
    ).run();
  } catch (e) {
    console.error('writeTelemetryD1: D1 telemetry write threw:', e && e.message);
  }
}

// Query telemetry -> Airtable "GTH MCP Query Log" (tblAZCSjdaJLbGh0L) -- the ENRICHED
// glanceable mirror. Restored 2026-06-23 (D558), enriched 2026-06-24 (D561). Non-blocking
// but NON-SILENT. Signal Score / Intent Class remain Airtable FORMULA fields (computed
// there, never written here). Referer + Limit Requested stay GTH-specific (read here).
async function logQuery(env, rec, request, args) {
  const atKey = env?.AIRTABLE_PAT;
  if (!atKey) { console.error('logQuery: AIRTABLE_PAT not bound -- GTH MCP telemetry write skipped'); return; }
  try {
    const res = await fetch(`https://api.airtable.com/v0/${AT_BASE}/${AT_LOG_TABLE}`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${atKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        records: [{ fields: {
          'Timestamp': rec.ts,
          'Tool Called': rec.tool,
          'State': rec.state || '',
          'City': rec.city || '',
          'Treatment Type': rec.treatment_type || '',
          'Insurance': rec.insurance || '',
          'Search Term': rec.search_term || '',
          'Results Count': (typeof rec.results_count === 'number') ? rec.results_count : 0,
          'Limit Requested': (args && args.limit) || 0,
          'Raw Args': rec.raw_args || '',
          'User Agent': rec.user_agent || '',
          'Source': rec.source || '',
          'Referer': request.headers.get('referer') || '',
          'API Key Tier': rec.api_key_tier || 'anonymous',
          'Caller Class': rec.caller_class,
          ...(rec.assistant_channel ? { 'Assistant Channel': rec.assistant_channel } : {}),
          'Session ID': rec.session_id || '',
          'Funnel Step': rec.funnel_step || '',
          'Zero Result': !!rec.zero_result,
          'Demand Cell': rec.demand_cell || '',
          'Facility Drilled': rec.vendor_drilled || '',
        }}],
        typecast: true
      })
    });
    if (!res.ok) {
      const detail = await res.text().catch(() => '');
      console.error(`logQuery: GTH MCP telemetry write failed ${res.status} ${detail.slice(0, 200)}`);
      await env?.GTH_CALL_METER?.put('telemetry_last_fail', new Date().toISOString(), { expirationTtl: 172800 }).catch(() => {});
    }
  } catch (e) {
    console.error('logQuery: GTH MCP telemetry write threw:', e && e.message);
    await env?.GTH_CALL_METER?.put('telemetry_last_fail', new Date().toISOString(), { expirationTtl: 172800 }).catch(() => {});
  }
}

async function recordSuccessfulCall(env, validation) {
  if (!validation.record) return;
  const updated = {
    ...validation.record,
    callsThisPeriod: (validation.record.callsThisPeriod || 0) + 1,
    lastUsedAt: new Date().toISOString(),
  };
  await env.GTH_API_KEYS.put(validation.apiKey, JSON.stringify(updated));

  if (validation.planSpec.reportUsage && validation.planSpec.meterEvent) {
    await postMeterEvent(env, validation.planSpec.meterEvent, validation.record.customerId);
  }
}

async function postMeterEvent(env, eventName, customerId) {
  const stripeKey = env?.STRIPE_SECRET_KEY;
  if (!stripeKey || !customerId) return;
  const identifier = `${eventName}-${customerId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
  const body = new URLSearchParams({
    event_name: eventName,
    'payload[stripe_customer_id]': customerId,
    'payload[value]': '1',
    identifier,
  });
  try {
    const res = await fetch('https://api.stripe.com/v1/billing/meter_events', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${stripeKey}`,
        'Content-Type': 'application/x-www-form-urlencoded',
        'Idempotency-Key': identifier,
      },
      body,
    });
    if (!res.ok) throw new Error(`meter event ${res.status}`);
  } catch (e) {
    // Queue for later retry. Drained by cbeg-usage-reporter Worker (Phase 3.6).
    await env.GTH_API_KEYS.put(
      `usage_retry:${Date.now()}:${identifier}`,
      JSON.stringify({ eventName, customerId, identifier, timestamp: Date.now() }),
      { expirationTtl: 86400 * 7 }
    ).catch(() => {});
  }
}

export async function onRequest(context) {
  const { request, env } = context;
  const url = new URL(request.url);

  // Only handle /mcp
  if (url.pathname !== "/mcp") {
    return env.ASSETS ? env.ASSETS.fetch(request) : new Response("Not Found", { status: 404 });
  }

  // Validate Origin on the MCP endpoint (DNS-rebinding protection; static assets above are unaffected)
  if (!originAllowed(request)) {
    return Response.json(jsonRpcError(null, -32600, "Origin not allowed"), { status: 403, headers: CORS_HEADERS });
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
      // Issue a server session id; the client echoes it via Mcp-Session-Id on subsequent
      // calls (the load-bearing session key for demand stitching). Exposed via CORS_HEADERS.
      return Response.json(jsonRpc(id, {
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: {
          name: "gettreatmenthelp",
          version: "1.1.1",
          description: "Find US addiction treatment facilities. 12,338 curated, SAMHSA-sourced. Filter by location, treatment type, and insurance accepted."
        }
      }), { headers: { ...CORS_HEADERS, 'Mcp-Session-Id': crypto.randomUUID() } });
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
      const validation = await validateKey(request, env);
      if (!validation.allowed) {
        return Response.json(
          jsonRpc(id, { content: [{ type: 'text', text: validation.reason }], isError: true }),
          { headers: CORS_HEADERS }
        );
      }
      const toolName = params?.name;
      const toolArgs = params?.arguments || {};
      const result = await handleToolCall(toolName, toolArgs, env);
      if (!result) {
        return Response.json(jsonRpcError(id, -32602, `Unknown tool: ${toolName}`), { headers: CORS_HEADERS });
      }
      // Strip the internal _resultsCount so it never reaches the client; pass it to telemetry.
      const { _resultsCount, ...clientResult } = result;

      // Enriched demand telemetry -> two INDEPENDENT non-blocking sinks (Airtable mirror +
      // D1 durable). allSettled so one sink's failure never skips the other; neither blocks
      // the tool response. Facility drill (the named facility a caller opened) is captured for
      // the directory-expansion / unmet-demand view only -- GTH has no paid/ranked placement.
      const tier = validation?.anonymous ? 'anonymous' : (validation?.record?.plan || 'keyed');
      const ids = (toolName === 'get_facility_detail') ? { drilled: toolArgs.name || '' } : null;
      const rec = await buildTelemetry('gth', request, env, toolName, toolArgs, _resultsCount, tier, ids);
      const telemetry = Promise.allSettled([logQuery(env, rec, request, toolArgs), writeTelemetryD1(env, rec)]);
      if (typeof context.waitUntil === 'function') context.waitUntil(telemetry); else await telemetry;

      if (!clientResult.isError) {
        const recording = recordSuccessfulCall(env, validation).catch(e => console.error('record failed:', e));
        if (typeof context.waitUntil === 'function') context.waitUntil(recording);
        else await recording;
      }
      return Response.json(jsonRpc(id, clientResult), { headers: CORS_HEADERS });
    }

    // Unknown method
    return Response.json(jsonRpcError(id, -32601, `Method not found: ${method}`), { headers: CORS_HEADERS });
  } catch (e) {
    return Response.json(jsonRpcError(id, -32603, e.message), { headers: CORS_HEADERS });
  }
}
