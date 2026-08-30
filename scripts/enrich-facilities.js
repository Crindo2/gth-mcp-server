#!/usr/bin/env node
// GTH Bulk Enrichment — One-Time Pass
// For each facility: Serper search (website + phone) → Claude Haiku (competitive description)
// Rate limit: 1 req/sec | Checkpoint every 100 facilities | Resume-capable
//
// Usage:
//   SERPER_API_KEY=xxx ANTHROPIC_API_KEY=xxx node scripts/enrich-facilities.js
//
// Estimated: ~3-4 hours for 12,373 facilities, ~$47 total cost

const fs = require("fs");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const DATA_FILE = path.join(PROJECT_ROOT, "facilities.json");
const CHECKPOINT_FILE = path.join(__dirname, "enrichment-checkpoint.json");
const CHECKPOINT_INTERVAL = 100;

const SERPER_KEY = process.env.SERPER_API_KEY;
const ANTHROPIC_KEY = process.env.ANTHROPIC_API_KEY;
const HAIKU_MODEL = "claude-haiku-4-5-20251001";

if (!SERPER_KEY) {
  console.error("ERROR: Set SERPER_API_KEY environment variable");
  process.exit(1);
}
if (!ANTHROPIC_KEY) {
  console.error("ERROR: Set ANTHROPIC_API_KEY environment variable");
  process.exit(1);
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

async function serperSearch(query) {
  const resp = await fetch("https://google.serper.dev/search", {
    method: "POST",
    headers: {
      "X-API-KEY": SERPER_KEY,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ q: query, num: 5 })
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Serper ${resp.status}: ${text.substring(0, 200)}`);
  }

  return resp.json();
}

async function haikuGenerate(prompt) {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": ANTHROPIC_KEY,
      "anthropic-version": "2023-06-01",
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: HAIKU_MODEL,
      max_tokens: 150,
      messages: [{ role: "user", content: prompt }]
    })
  });

  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Haiku ${resp.status}: ${text.substring(0, 200)}`);
  }

  const data = await resp.json();
  return (data.content && data.content[0] && data.content[0].text) || "";
}

function extractWebsite(serperResults) {
  const organic = serperResults.organic || [];
  for (const r of organic) {
    const url = (r.link || "").toLowerCase();
    // Skip directories, social media, review sites
    if (url.includes("yelp.com") || url.includes("facebook.com") ||
        url.includes("healthgrades.com") || url.includes("google.com") ||
        url.includes("samhsa.gov") || url.includes("findtreatment.gov") ||
        url.includes("yellowpages.com") || url.includes("bbb.org") ||
        url.includes("linkedin.com") || url.includes("gettreatmenthelp.com")) {
      continue;
    }
    // Likely the facility's own website
    return r.link;
  }
  return "";
}

function extractPhone(serperResults) {
  // Check knowledge graph
  const kg = serperResults.knowledgeGraph || {};
  if (kg.phoneNumber) return kg.phoneNumber;
  if (kg.phone) return kg.phone;

  // Check organic snippets for phone patterns
  const organic = serperResults.organic || [];
  for (const r of organic) {
    const snippet = (r.snippet || "") + " " + (r.title || "");
    const phoneMatch = snippet.match(/\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}/);
    if (phoneMatch) return phoneMatch[0];
  }

  return "";
}

function loadCheckpoint() {
  if (fs.existsSync(CHECKPOINT_FILE)) {
    return JSON.parse(fs.readFileSync(CHECKPOINT_FILE, "utf-8"));
  }
  return { completed: {}, lastIndex: 0 };
}

function saveCheckpoint(checkpoint) {
  fs.writeFileSync(CHECKPOINT_FILE, JSON.stringify(checkpoint));
}

async function enrichFacility(facility) {
  const query = `"${facility.name}" ${facility.city} ${facility.stateAbbr} treatment center`;

  // Step 1: Serper search
  const serperResults = await serperSearch(query);
  const website = extractWebsite(serperResults);
  const phone = extractPhone(serperResults);

  await sleep(500); // Half-second between API calls

  // Step 2: Claude Haiku description
  const types = (facility.types || []).join(", ");
  const prompt = `Write exactly 2 plain-text sentences (no markdown, no headers, no bullet points) describing ${facility.name} in ${facility.city}, ${facility.state} as a competitive treatment option. They offer: ${types}. Focus on what makes them a strong choice for patients seeking treatment in this market. Be specific and factual. Do not use marketing language or superlatives.`;

  const description = await haikuGenerate(prompt);

  await sleep(500); // Rate limiting

  return {
    website: website || facility.website || "",
    phone: phone || facility.phone || "Call for information",
    description: description.trim() || facility.description || ""
  };
}

async function main() {
  console.log("=== GTH Bulk Enrichment ===");
  console.log(`Date: ${new Date().toISOString()}`);
  console.log(`Model: ${HAIKU_MODEL}`);
  console.log();

  // Load data
  const facilities = JSON.parse(fs.readFileSync(DATA_FILE, "utf-8"));
  console.log(`Loaded ${facilities.length} facilities`);

  // Load checkpoint
  const checkpoint = loadCheckpoint();
  const completedKeys = new Set(Object.keys(checkpoint.completed));
  const startIndex = checkpoint.lastIndex || 0;
  console.log(`Checkpoint: ${completedKeys.size} already enriched, resuming from index ${startIndex}`);

  let enriched = 0;
  let failed = 0;
  let skipped = 0;
  const startTime = Date.now();

  for (let i = startIndex; i < facilities.length; i++) {
    const f = facilities[i];
    const key = `${f.name}|${f.city}|${f.stateAbbr}`;

    // Skip if already enriched in this run
    if (completedKeys.has(key)) {
      skipped++;
      continue;
    }

    try {
      const result = await enrichFacility(f);

      // Update facility
      f.website = result.website;
      f.phone = result.phone;
      f.description = result.description;
      f.curated = true;

      checkpoint.completed[key] = true;
      enriched++;

      // Progress logging
      if (enriched % 10 === 0) {
        const elapsed = (Date.now() - startTime) / 1000;
        const rate = enriched / elapsed;
        const remaining = (facilities.length - i - 1) / rate;
        process.stdout.write(
          `\r  ${enriched + skipped}/${facilities.length} | ` +
          `${enriched} enriched | ${failed} failed | ` +
          `${rate.toFixed(1)}/sec | ~${(remaining / 60).toFixed(0)}min remaining`
        );
      }

      // Checkpoint
      if (enriched % CHECKPOINT_INTERVAL === 0) {
        checkpoint.lastIndex = i;
        saveCheckpoint(checkpoint);
        // Also save intermediate data
        fs.writeFileSync(DATA_FILE, JSON.stringify(facilities));
        console.log(`\n  Checkpoint saved at index ${i} (${enriched} enriched)`);
      }
    } catch (err) {
      failed++;
      console.error(`\n  FAIL [${i}] ${f.name} (${f.city}, ${f.stateAbbr}): ${err.message}`);

      // If too many consecutive failures, pause
      if (failed > 50 && enriched === 0) {
        console.error("Too many failures with no successes. Check API keys.");
        process.exit(1);
      }

      // Rate limit error — back off
      if (err.message.includes("429") || err.message.includes("rate")) {
        console.log("  Rate limited. Waiting 30 seconds...");
        await sleep(30000);
      }
    }
  }

  // Final save
  fs.writeFileSync(DATA_FILE, JSON.stringify(facilities));
  console.log(`\n\n=== Enrichment Complete ===`);
  console.log(`  Enriched: ${enriched}`);
  console.log(`  Failed: ${failed}`);
  console.log(`  Skipped (checkpoint): ${skipped}`);
  console.log(`  Total time: ${((Date.now() - startTime) / 1000 / 60).toFixed(1)} minutes`);
  console.log(`  Output: ${DATA_FILE}`);

  // Clean up checkpoint on success
  if (failed === 0) {
    fs.unlinkSync(CHECKPOINT_FILE);
    console.log("  Checkpoint cleaned up (complete run).");
  } else {
    console.log(`  Checkpoint preserved (${failed} failures). Re-run to retry.`);
  }
}

main().catch(err => {
  console.error("FATAL:", err.message);
  process.exit(1);
});
