# GTH Intelligence — Substance Abuse Treatment Finder

An MCP server providing AI agents with access to 12,373 SAMHSA-verified substance abuse treatment facilities across all 50 US states. The only fully enriched, actively maintained SAMHSA MCP server available.

## What It Does

The GTH Intelligence MCP server gives AI agents structured access to the GetTreatmentHelp database of substance abuse and mental health treatment facilities — enriched with descriptions, verified phone numbers, websites, and competitive intelligence data.

## Tools

### `search_facilities`
Search for addiction treatment and mental health facilities. Filter by US state, city, treatment type, and insurance. Returns facility names, locations, programs, insurance, phone numbers, and direct links.

**Parameters:**
- `zip` — ZIP code to search near
- `state` — Two-letter state abbreviation
- `city` — City name
- `treatment_type` — Type of treatment (e.g. "detox", "inpatient", "outpatient", "MAT")
- `insurance` — Insurance accepted
- `radius` — Search radius in miles (default 25)
- `limit` — Max results to return

### `get_facility_detail`
Get detailed information about a specific treatment facility by name. Returns programs offered, insurance accepted, phone number, website, and description.

**Parameters:**
- `name` (required) — Facility name

### `list_states`
List all US states that have treatment facility data available, with facility count per state.

### `get_treatment_types`
Get definitions and explanations of all treatment program types (Inpatient, Detox, IOP, PHP, Outpatient, MAT, Counseling, Sober Living).

## Usage

### MCP Endpoint
```
https://gth-mcp-server.pages.dev/mcp
```

### Connect via Claude Desktop
Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "gth-intelligence": {
      "command": "npx",
      "args": ["-y", "@smithery/cli@latest", "run", "cbeggroup/gettreatmenthelp", "--key", "YOUR_SMITHERY_KEY"]
    }
  }
}
```

### Connect via Smithery
```bash
smithery mcp add cbeggroup/gettreatmenthelp
```

## Data Coverage

- **12,373** SAMHSA-verified substance abuse treatment facilities
- **All 50 states** + DC
- **100%** description coverage
- **99.9%** website coverage
- **99.2%** verified phone numbers
- Monthly data refreshes from SAMHSA

## Use Cases

- Help patients find nearby treatment options
- Build competitive intelligence tools for treatment operators
- Power facility finder features in healthcare apps
- Research treatment availability by geography or program type

## API Access

Free tier: 10 calls/month — no API key required.

Paid tiers available at [gettreatmenthelp.com/api-access/](https://www.gettreatmenthelp.com/api-access/)

## Links

- **Homepage:** [gettreatmenthelp.com](https://www.gettreatmenthelp.com)
- **For Operators:** [gettreatmenthelp.com/for-operators/](https://www.gettreatmenthelp.com/for-operators/)
- **Smithery:** [smithery.ai/server/cbeggroup/gettreatmenthelp](https://smithery.ai/server/cbeggroup/gettreatmenthelp)
- **MCP Registry:** [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io/v0.1/servers?search=gettreatmenthelp)

## License

MIT
