# GTH Intelligence - Substance Abuse Treatment Finder

An MCP server that gives AI agents access to 12,338 curated US addiction treatment facilities, sourced from SAMHSA, across all 50 states. Built for treatment operators, healthcare AI developers, and anyone building tools that help people find care.

## What It Does

The GTH Intelligence MCP server provides structured access to GetTreatmentHelp's directory of addiction treatment facilities -- enriched with descriptions, phone numbers, websites, programs offered, and insurance accepted.

## Tools

### `search_facilities`
Search for addiction treatment facilities. Filter by US state (required), city, treatment type, and insurance accepted. Returns facility names, locations, programs, insurance, phone numbers, and a browse URL.

**Parameters:**
- `state` (required) -- US state name or two-letter abbreviation (e.g. "California" or "CA")
- `city` -- City name (partial match supported)
- `treatment_type` -- One of: Inpatient Rehab, Outpatient, Detox, IOP (Intensive Outpatient), PHP (Partial Hospitalization), MAT (Medication-Assisted Treatment), Counseling, Sober Living
- `insurance` -- Insurance provider accepted (e.g. "Medicaid", "Aetna", "Medicare")
- `limit` -- Max results to return (1-20, default 5)

### `get_facility_detail`
Get the full profile of one treatment facility by name: location, phone, programs offered, insurance accepted, and a browse URL. Partial name matching supported.

**Parameters:**
- `name` (required) -- Full or partial facility name

### `list_states`
List every US state with treatment facility data, with per-state facility counts.

### `get_treatment_types`
Get definitions of all treatment program types (Inpatient Rehab, Detox, PHP, IOP, Outpatient, MAT, Counseling, Sober Living) with duration, intensity, and typical fit.

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
      "args": ["-y", "mcp-remote", "https://gth-mcp-server.pages.dev/mcp"]
    }
  }
}
```
No API key required.

## Data Coverage

- **12,338** curated addiction treatment facilities, sourced from SAMHSA
- **All 50 states** + DC
- Programs, insurance accepted, phone numbers, and browse links per facility
- Monthly data refreshes from SAMHSA

## Use Cases

- Help people find nearby treatment options
- Build facility-finder features into healthcare apps
- Power competitive intelligence tools for treatment operators
- Research treatment availability by geography or program type

## API Access

Free: 100 calls per IP per day, no API key required.

For higher-volume access, get in touch via [gettreatmenthelp.com/api-access/](https://www.gettreatmenthelp.com/api-access/)

## Links

- **Homepage:** [gettreatmenthelp.com](https://www.gettreatmenthelp.com)
- **For Operators:** [gettreatmenthelp.com/for-operators/](https://www.gettreatmenthelp.com/for-operators/)
- **MCP Registry:** [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io)

## License

MIT
