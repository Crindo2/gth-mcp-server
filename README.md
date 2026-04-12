# GTH Intelligence — Substance Abuse Treatment Finder

[![smithery badge](https://smithery.ai/badge/cbeggroup/gettreatmenthelp)](https://smithery.ai/servers/cbeggroup/gettreatmenthelp)

A Model Context Protocol (MCP) server that gives AI agents real-time access to **12,373 SAMHSA-verified substance abuse treatment facilities** across all 50 US states. Built for treatment center operators, healthcare AI developers, and anyone building tools in the behavioral health space.

## What You Can Do With It

- Search treatment facilities near any US zip code within a configurable radius
- Filter by level of care: detox, residential, IOP, outpatient, MAT
- Get facility details including phone numbers, services, and insurance accepted
- List all US states with available treatment data and facility counts
- Understand treatment program types with plain-language definitions

## MCP Endpoint

```
https://gth-mcp-server.pages.dev/mcp
```

**Transport:** SSE (Server-Sent Events)

## Quick Connect

### Claude Desktop

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

### Smithery CLI

```bash
smithery mcp add cbeggroup/gettreatmenthelp
```

### Cursor / Windsurf

Add to your MCP settings:

```json
{
  "name": "GTH Intelligence",
  "url": "https://gth-mcp-server.pages.dev/mcp"
}
```

## Available Tools

### `search_facilities`
Search for addiction treatment and mental health facilities by location, treatment type, and insurance.

**Parameters:**
- `zip` (string) — US zip code to search near
- `radius` (number, optional) — Search radius in miles (default: 25)
- `type` (string, optional) — Treatment type filter (e.g., `SA` for substance abuse)
- `limit` (number, optional) — Max results to return (default: 20)

**Example prompts:**
- *"Find all IOP facilities within 25 miles of 75208"*
- *"What detox centers are available near zip code 90210?"*
- *"Show me MAT providers in the Dallas area"*

---

### `get_facility_detail`
Get detailed information about a specific treatment facility by name.

**Example prompts:**
- *"Get details for Parkland Hospital treatment center"*
- *"What insurance does [facility name] accept?"*

---

### `list_states`
List all US states with available treatment facility data and counts.

**Example prompts:**
- *"Which states have the most treatment facilities?"*
- *"How many facilities are in Wyoming?"*

---

### `get_treatment_types`
Get plain-language definitions of all treatment program types to help users understand their options.

**Example prompts:**
- *"What's the difference between IOP and outpatient?"*
- *"Explain what MAT treatment is"*
- *"What levels of care are available for addiction treatment?"*

## Example Use Cases

**For treatment operators:**
```
"How many IOP providers operate within 30 miles of our Dallas facility?"
"Show me the competitive landscape for residential treatment in Phoenix"
"What markets have the fewest detox centers in Texas?"
```

**For patient navigation:**
```
"Find treatment centers near 30301 that accept Medicaid"
"What residential treatment options are available in rural Wyoming?"
"Show me all facilities within 10 miles of zip 77001"
```

**For researchers and developers:**
```
"List all states with fewer than 10 MAT providers"
"How many SAMHSA-verified facilities are in each state?"
```

## Data Source

Facility data is sourced from the **Substance Abuse and Mental Health Services Administration (SAMHSA)** Treatment Locator, filtered to substance abuse (`sType=sa`) facilities only. Dataset covers **12,373 facilities** across all 50 states. Data is refreshed monthly.

## Who It's For

- **Treatment center operators** doing competitive intelligence and market research
- **Healthcare AI developers** building patient navigation and referral tools
- **Researchers** studying treatment access gaps and facility distribution
- **Care coordinators** helping patients find appropriate level-of-care placements

## Related Resources

- [GTH Intelligence Platform](https://gettreatmenthelp.com)
- [API Access & Operator Tiers](https://gettreatmenthelp.com/api-access/)
- [MCP Setup Guide](https://gettreatmenthelp.com/mcp-guide/)
- [Smithery Listing](https://smithery.ai/servers/cbeggroup/gettreatmenthelp)

## License

MIT
