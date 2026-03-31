# GetTreatmentHelp MCP Server

Search 11,271 SAMHSA-verified US addiction treatment and mental health facilities by location, treatment type, and insurance.

## Live MCP Endpoint

```
https://gth-mcp-server.pages.dev/mcp
```

**No API key required. Free access.**

## Connect to Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gettreatmenthelp": {
      "url": "https://gth-mcp-server.pages.dev/mcp",
      "type": "http"
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `search_facilities` | Search by state, city, treatment type, and insurance |
| `get_facility_detail` | Full details on a specific facility by name |
| `list_states` | All 51 jurisdictions with facility counts |
| `get_treatment_types` | Plain-English definitions of all treatment program types |

## Example Queries

- "Find inpatient rehab in Texas that takes Medicaid"
- "What detox centers are near Chicago?"
- "Show me MAT programs in Ohio that accept Medicare"
- "Find sober living homes in Los Angeles"

## Dataset

- **11,271 facilities** — all 50 states + DC
- Source: [SAMHSA FindTreatment.gov](https://findtreatment.gov) (real phone numbers, addresses, lat/long)
- Treatment types: Inpatient, Detox, IOP, PHP, MAT, Outpatient, Counseling, Sober Living
- Insurance: Medicaid, Medicare, Tricare, private pay, sliding scale

## Powered By

[GetTreatmentHelp.com](https://gettreatmenthelp.com)

---

🆘 **SAMHSA National Helpline: 1-800-662-4357** (free, confidential, 24/7)
