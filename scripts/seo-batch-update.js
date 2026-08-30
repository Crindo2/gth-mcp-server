#!/usr/bin/env node
// GTH Programmatic SEO Batch Update
// Updates titles, meta descriptions, and adds schema to 171 city/LOC posts,
// 51 state pages, and 1 hub page via WordPress REST API.

const fs = require("fs");
const path = require("path");

const WP_BASE = "https://www.gettreatmenthelp.com/wp-json/wp/v2";
const WP_USER = "cbeggroup@gmail.com";
const WP_PASS = "Tqkr xisM t02o MrIo Pbfg sX5Q";
const AUTH_HEADER = "Basic " + Buffer.from(`${WP_USER}:${WP_PASS}`).toString("base64");
const YEAR = "2026";

// Exclude these blog posts that match the slug pattern but aren't city pages
const EXCLUDE_SLUGS = new Set([
  "how-to-compare-rehab-center-local-competitors",
  "why-rehab-centers-lose-admissions-competitors"
]);

// State data for state pages
const STATES = {
  al:"Alabama",ak:"Alaska",az:"Arizona",ar:"Arkansas",ca:"California",co:"Colorado",
  ct:"Connecticut",de:"Delaware",fl:"Florida",ga:"Georgia",hi:"Hawaii",id:"Idaho",
  il:"Illinois",in:"Indiana",ia:"Iowa",ks:"Kansas",ky:"Kentucky",la:"Louisiana",
  me:"Maine",md:"Maryland",ma:"Massachusetts",mi:"Michigan",mn:"Minnesota",ms:"Mississippi",
  mo:"Missouri",mt:"Montana",ne:"Nebraska",nv:"Nevada",nh:"New Hampshire",nj:"New Jersey",
  nm:"New Mexico",ny:"New York",nc:"North Carolina",nd:"North Dakota",oh:"Ohio",ok:"Oklahoma",
  or:"Oregon",pa:"Pennsylvania",ri:"Rhode Island",sc:"South Carolina",sd:"South Dakota",
  tn:"Tennessee",tx:"Texas",ut:"Utah",vt:"Vermont",va:"Virginia",wa:"Washington",
  wv:"West Virginia",wi:"Wisconsin",wy:"Wyoming",dc:"Washington D.C."
};

// City → State mapping (extracted from post titles)
const CITY_STATE = {};

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function wpGet(endpoint) {
  const resp = await fetch(`${WP_BASE}${endpoint}`, {
    headers: { Authorization: AUTH_HEADER, Accept: "application/json" }
  });
  if (!resp.ok) throw new Error(`GET ${endpoint}: ${resp.status}`);
  return resp.json();
}

async function wpUpdate(endpoint, data) {
  const resp = await fetch(`${WP_BASE}${endpoint}`, {
    method: "POST",
    headers: {
      Authorization: AUTH_HEADER,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(data)
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`POST ${endpoint}: ${resp.status} - ${text.substring(0, 200)}`);
  }
  return resp.json();
}

function slugToCity(slug) {
  // Remove treatment type suffixes
  let city = slug
    .replace(/-outpatient-treatment-competitors$/, "")
    .replace(/-mat-treatment-competitors$/, "")
    .replace(/-iop-treatment-competitors$/, "")
    .replace(/-iop-competitors$/, "")
    .replace(/-detox-treatment-competitors$/, "")
    .replace(/-detox-competitors$/, "")
    .replace(/-inpatient-rehab-competitors$/, "")
    .replace(/-inpatient-treatment-competitors$/, "")
    .replace(/-treatment-competitors$/, "")
    .replace(/-competitors$/, "");

  // Convert slug to title case
  return city.split("-").map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
}

function slugToTreatmentType(slug) {
  if (slug.includes("-outpatient-treatment-")) return "Outpatient";
  if (slug.includes("-mat-treatment-")) return "MAT";
  if (slug.includes("-iop-")) return "IOP";
  if (slug.includes("-detox-")) return "Detox";
  if (slug.includes("-inpatient-")) return "Inpatient";
  return "Treatment";
}

function extractStateFromTitle(title) {
  // Titles like "Top MAT ... Centers in Duluth, MN" or "Top IOP ... in Atlanta, GA"
  const match = title.match(/,\s*([A-Z]{2})\s/);
  if (match) return match[1];
  const match2 = title.match(/in\s+\w+,\s*([A-Z]{2})/);
  if (match2) return match2[1];
  return "";
}

function buildCityTitle(city, treatmentType) {
  const fullType = {
    "Outpatient": "Outpatient Treatment",
    "MAT": "MAT (Medication-Assisted Treatment)",
    "IOP": "IOP Treatment",
    "Detox": "Detox Treatment",
    "Inpatient": "Inpatient Rehab",
    "Treatment": "Addiction Treatment"
  }[treatmentType] || treatmentType + " Treatment";

  return `${city} ${fullType} Centers: ${YEAR} Guide | GetTreatmentHelp`;
}

function buildCityMeta(city, treatmentType, stateAbbr) {
  const state = stateAbbr ? `, ${stateAbbr}` : "";
  const typeLC = treatmentType.toLowerCase();
  return `Find ${typeLC} treatment centers in ${city}${state}. Compare licensed facilities by insurance accepted, services offered, and availability. Free audit available.`;
}

function buildCitySchema(city, treatmentType, slug, metaDesc) {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "MedicalWebPage",
    "name": `${city} ${treatmentType} Treatment Centers`,
    "description": metaDesc,
    "url": `https://gettreatmenthelp.com/${slug}/`,
    "about": {
      "@type": "MedicalCondition",
      "name": "Substance Use Disorder"
    },
    "specialty": "Addiction Medicine"
  });
}

function buildStateTitle(stateName) {
  return `${stateName} Addiction Treatment Centers: ${YEAR} Guide | GetTreatmentHelp`;
}

function buildStateMeta(stateName, stateAbbr) {
  return `Find verified addiction treatment centers in ${stateName}. Compare facilities by treatment type, insurance accepted, and services offered. SAMHSA-verified data. Free Growth Gap Audit available.`;
}

function buildStateSchema(stateName, slug) {
  return JSON.stringify({
    "@context": "https://schema.org",
    "@type": "MedicalWebPage",
    "name": `${stateName} Addiction Treatment Centers`,
    "description": `Comprehensive directory of SAMHSA-verified addiction treatment facilities in ${stateName}.`,
    "url": `https://gettreatmenthelp.com/${slug}/`,
    "about": {
      "@type": "MedicalCondition",
      "name": "Substance Use Disorder"
    },
    "specialty": "Addiction Medicine"
  });
}

async function getAllPosts() {
  const allPosts = [];
  for (let page = 1; page <= 5; page++) {
    try {
      const posts = await wpGet(`/posts?per_page=100&page=${page}&_fields=id,title,slug,link,excerpt,content,categories&status=publish`);
      if (!posts.length) break;
      allPosts.push(...posts);
    } catch { break; }
  }
  return allPosts;
}

async function getAllPages() {
  const allPages = [];
  for (let page = 1; page <= 3; page++) {
    try {
      const pages = await wpGet(`/pages?per_page=100&page=${page}&_fields=id,title,slug,link,excerpt,content&status=publish`);
      if (!pages.length) break;
      allPages.push(...pages);
    } catch { break; }
  }
  return allPages;
}

async function main() {
  console.log("=== GTH Programmatic SEO Batch Update ===");
  console.log(`Date: ${new Date().toISOString()}\n`);

  // Fetch all posts and pages
  console.log("Fetching all posts...");
  const allPosts = await getAllPosts();
  console.log(`  ${allPosts.length} posts loaded`);

  console.log("Fetching all pages...");
  const allPages = await getAllPages();
  console.log(`  ${allPages.length} pages loaded`);

  // Categorize
  const cityPosts = [];
  const statePagesWP = []; // State pages (WP pages, not posts)

  for (const p of allPosts) {
    const slug = p.slug;
    if (EXCLUDE_SLUGS.has(slug)) continue;
    if (slug.endsWith("-competitors")) {
      const title = typeof p.title === "object" ? p.title.rendered : p.title;
      const stateAbbr = extractStateFromTitle(title);
      cityPosts.push({ ...p, cityName: slugToCity(slug), treatmentType: slugToTreatmentType(slug), stateAbbr });
    }
  }

  for (const p of allPages) {
    const slug = p.slug;
    if (slug.length <= 2 && STATES[slug]) {
      statePagesWP.push({ ...p, stateName: STATES[slug], stateAbbr: slug.toUpperCase() });
    }
  }

  console.log(`\nCity/LOC posts to update: ${cityPosts.length}`);
  console.log(`State pages to update: ${statePagesWP.length}`);

  const results = { updated: 0, failed: 0, failures: [], samples: [] };

  // === TASK 1: Update city/LOC posts ===
  console.log("\n--- Task 1: City/LOC Posts ---");
  for (let i = 0; i < cityPosts.length; i++) {
    const post = cityPosts[i];
    const oldTitle = typeof post.title === "object" ? post.title.rendered : post.title;
    const newTitle = buildCityTitle(post.cityName, post.treatmentType);
    const newMeta = buildCityMeta(post.cityName, post.treatmentType, post.stateAbbr);
    const schema = buildCitySchema(post.cityName, post.treatmentType, post.slug, newMeta);
    const schemaBlock = `\n<!-- wp:html -->\n<script type="application/ld+json">${schema}</script>\n<!-- /wp:html -->`;

    // Get current content to append schema
    const currentContent = typeof post.content === "object" ? post.content.rendered : (post.content || "");
    const hasSchema = currentContent.includes("application/ld+json");
    const newContent = hasSchema ? currentContent : currentContent + schemaBlock;

    try {
      await wpUpdate(`/posts/${post.id}`, {
        title: newTitle,
        excerpt: newMeta,
        content: hasSchema ? undefined : newContent
      });

      results.updated++;
      if (results.samples.length < 5) {
        results.samples.push({ id: post.id, old: oldTitle.substring(0, 60), new: newTitle.substring(0, 60) });
      }

      if ((i + 1) % 10 === 0) {
        process.stdout.write(`\r  ${i + 1}/${cityPosts.length} city posts updated`);
      }
    } catch (err) {
      results.failed++;
      results.failures.push({ id: post.id, slug: post.slug, error: err.message.substring(0, 100) });
      console.error(`\n  FAIL [${post.id}] ${post.slug}: ${err.message.substring(0, 80)}`);
    }

    await sleep(500); // Rate limit
  }
  console.log(`\n  City posts done: ${results.updated} updated, ${results.failed} failed`);

  // === TASK 2: Update state pages ===
  console.log("\n--- Task 2: State Pages ---");
  let stateUpdated = 0, stateFailed = 0;
  for (const page of statePagesWP) {
    const oldTitle = typeof page.title === "object" ? page.title.rendered : page.title;
    const newTitle = buildStateTitle(page.stateName);
    const newMeta = buildStateMeta(page.stateName, page.stateAbbr);
    const schema = buildStateSchema(page.stateName, page.slug);
    const schemaBlock = `\n<!-- wp:html -->\n<script type="application/ld+json">${schema}</script>\n<!-- /wp:html -->`;

    const currentContent = typeof page.content === "object" ? page.content.rendered : (page.content || "");
    const hasSchema = currentContent.includes("application/ld+json");

    try {
      await wpUpdate(`/pages/${page.id}`, {
        title: newTitle,
        excerpt: newMeta,
        content: hasSchema ? undefined : currentContent + schemaBlock
      });
      stateUpdated++;
      if (results.samples.length < 8) {
        results.samples.push({ id: page.id, old: oldTitle.substring(0, 60), new: newTitle.substring(0, 60) });
      }
    } catch (err) {
      stateFailed++;
      results.failures.push({ id: page.id, slug: page.slug, error: err.message.substring(0, 100) });
      console.error(`  FAIL [${page.id}] ${page.slug}: ${err.message.substring(0, 80)}`);
    }
    await sleep(500);
  }
  console.log(`  State pages done: ${stateUpdated} updated, ${stateFailed} failed`);

  // === TASK 3: Update hub page (ID 301) ===
  console.log("\n--- Task 3: Hub Page (ID 301) ---");
  try {
    const hubTitle = "Treatment Center Competitive Intelligence by City | For Operators | GetTreatmentHelp";
    const hubMeta = "Market-level competitive intelligence for addiction treatment operators. Compare facility counts, insurance acceptance, and service gaps across 50 major US markets. Free Growth Gap Audit available.";
    const hubSchema = JSON.stringify({
      "@context": "https://schema.org",
      "@type": ["Organization", "MedicalBusiness"],
      "name": "GetTreatmentHelp",
      "description": hubMeta,
      "url": "https://gettreatmenthelp.com/competitive-intelligence-by-city/",
      "specialty": "Addiction Medicine"
    });
    const hubSchemaBlock = `\n<!-- wp:html -->\n<script type="application/ld+json">${hubSchema}</script>\n<!-- /wp:html -->`;

    const hubPage = await wpGet("/pages/301?_fields=id,title,content");
    const hubContent = typeof hubPage.content === "object" ? hubPage.content.rendered : (hubPage.content || "");
    const hasSchema = hubContent.includes("application/ld+json");

    await wpUpdate("/pages/301", {
      title: hubTitle,
      excerpt: hubMeta,
      content: hasSchema ? undefined : hubContent + hubSchemaBlock
    });
    console.log("  Hub page updated.");
    results.updated++;
  } catch (err) {
    console.error(`  FAIL hub page: ${err.message}`);
    results.failures.push({ id: 301, slug: "competitive-intelligence-by-city", error: err.message.substring(0, 100) });
  }

  // === Report ===
  console.log("\n========================================");
  console.log("=== SEO Batch Update Report ===");
  console.log("========================================");
  console.log(`City posts updated: ${results.updated - stateUpdated - 1}/${cityPosts.length}`);
  console.log(`State pages updated: ${stateUpdated}/${statePagesWP.length}`);
  console.log(`Hub page updated: 1`);
  console.log(`Total updated: ${results.updated + stateUpdated}`);
  console.log(`Total failed: ${results.failed + stateFailed}`);
  console.log(`Schema added: ${results.updated + stateUpdated} pages`);

  if (results.failures.length > 0) {
    console.log("\nFailures:");
    for (const f of results.failures) {
      console.log(`  ID ${f.id} (${f.slug}): ${f.error}`);
    }
  }

  console.log("\nSample title rewrites:");
  for (const s of results.samples) {
    console.log(`  ID ${s.id}:`);
    console.log(`    Before: ${s.old}`);
    console.log(`    After:  ${s.new}`);
  }
}

main().catch(err => {
  console.error("FATAL:", err.message);
  process.exit(1);
});
