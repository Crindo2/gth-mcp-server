#!/usr/bin/env node
// GTH SAMHSA Data Fetcher — Excel Bulk Download Approach
// Downloads the SAMHSA National Directory of SA Facilities (Excel),
// transforms to GTH schema, merges with existing enrichment, saves to facilities.json
//
// NOTE: Merge uses exact name+city+state matching. ~1,600 records in the existing
// enriched dataset have name/city spellings that differ from the SAMHSA Excel
// (e.g. "St." vs "Saint", abbreviations, DBA names). These existing records are
// preserved via the merge but won't match new SAMHSA data. This is acceptable.
// TODO (future): Add fuzzy matching (Levenshtein distance or normalized tokens)
// to close the ~13% gap between SAMHSA Excel (12,176) and enriched set (12,373).

const fs = require("fs");
const path = require("path");

const SAMHSA_XLSX_URL = "https://www.samhsa.gov/data/sites/default/files/reports/rpt35993/SA%20facilites/SU%20Directory/National_Directory_SA_Facilities_2022.xlsx";
const PROJECT_ROOT = path.resolve(__dirname, "..");
const OUTPUT_FILE = path.join(PROJECT_ROOT, "facilities.json");
const TEMP_XLSX = path.join(__dirname, "samhsa-download.xlsx");
const MAX_FILE_SIZE = 24 * 1024 * 1024;

// State abbreviation → full name
const STATE_NAMES = {
  AL:"Alabama",AK:"Alaska",AZ:"Arizona",AR:"Arkansas",CA:"California",CO:"Colorado",
  CT:"Connecticut",DE:"Delaware",FL:"Florida",GA:"Georgia",HI:"Hawaii",ID:"Idaho",
  IL:"Illinois",IN:"Indiana",IA:"Iowa",KS:"Kansas",KY:"Kentucky",LA:"Louisiana",
  ME:"Maine",MD:"Maryland",MA:"Massachusetts",MI:"Michigan",MN:"Minnesota",MS:"Mississippi",
  MO:"Missouri",MT:"Montana",NE:"Nebraska",NV:"Nevada",NH:"New Hampshire",NJ:"New Jersey",
  NM:"New Mexico",NY:"New York",NC:"North Carolina",ND:"North Dakota",OH:"Ohio",OK:"Oklahoma",
  OR:"Oregon",PA:"Pennsylvania",RI:"Rhode Island",SC:"South Carolina",SD:"South Dakota",
  TN:"Tennessee",TX:"Texas",UT:"Utah",VT:"Vermont",VA:"Virginia",WA:"Washington",
  WV:"West Virginia",WI:"Wisconsin",WY:"Wyoming",DC:"District of Columbia",
  AS:"American Samoa",GU:"Guam",MP:"Northern Mariana Islands",PR:"Puerto Rico",VI:"US Virgin Islands"
};

// SAMHSA service codes → GTH treatment types
const TYPE_MAP = {
  // Service Settings (SET category)
  HI:  "Inpatient Rehab",
  HID: "Detox",
  HIT: "Inpatient Rehab",
  RES: "Inpatient Rehab",
  RS:  "Inpatient Rehab",
  RL:  "Inpatient Rehab",
  RD:  "Detox",
  OP:  "Outpatient",
  ORT: "Outpatient",
  OIT: "IOP (Intensive Outpatient)",
  ODT: "PHP (Partial Hospitalization)",
  OD:  "Detox",
  OMB: "MAT (Medication-Assisted Treatment)",
  // Type of Care
  DT:  "Detox",
  SA:  null, // Too generic, skip
  HH:  "Sober Living",
  SUMH: null, // Co-occurring, not a specific type
  // Opioid Treatment
  MU:  "MAT (Medication-Assisted Treatment)",
  BU:  "MAT (Medication-Assisted Treatment)",
  NU:  "MAT (Medication-Assisted Treatment)",
  OTP: "MAT (Medication-Assisted Treatment)",
  BUM: "MAT (Medication-Assisted Treatment)",
  MM:  "MAT (Medication-Assisted Treatment)",
  // Treatment Approaches (TAP)
  CBT: "Counseling",
  MOTI: "Counseling",
  MXM: "Counseling",
  RELP: "Counseling",
  TELE: "Counseling",
};

// SAMHSA payment codes → GTH insurance names
const INSURANCE_MAP = {
  MC:  "Medicare",
  MD:  "Medicaid",
  PI:  "Private Insurance",
  MI:  "Military Insurance (TRICARE)",
  SF:  "Cash/Self-Pay",
  SI:  "State Insurance",
  FSA: "Government Funded",
  NP:  null, // "No payment" — skip
  ITU: "IHS/Tribal Funds",
  SAMF: null, // Internal funding, skip
};

function parseServiceCodes(codeStr) {
  if (!codeStr) return { types: ["Outpatient"], insurance: ["Call for information"] };

  const codes = codeStr.split(/[\s*]+/).filter(Boolean);
  const types = new Set();
  const insurance = [];

  for (const code of codes) {
    const uc = code.toUpperCase();
    if (TYPE_MAP[uc]) types.add(TYPE_MAP[uc]);
    if (INSURANCE_MAP[uc]) insurance.push(INSURANCE_MAP[uc]);
  }

  // Check for specific MAT indicators
  if (codes.some(c => ["MU","BU","NU","OTP","BUM","MM","PMAT"].includes(c.toUpperCase()))) {
    types.add("MAT (Medication-Assisted Treatment)");
  }

  return {
    types: types.size > 0 ? [...types] : ["Outpatient"],
    insurance: insurance.length > 0 ? insurance : ["Call for information"]
  };
}

function transformRow(row) {
  const [name1, name2, street1, street2, city, state, zip, phone, intake1, intake2, intake1a, intake2a, serviceCodes] = row;

  if (!name1 || !state) return null;

  const stateAbbr = (state || "").toUpperCase().trim();
  const { types, insurance } = parseServiceCodes(serviceCodes);

  return {
    name: (name1 || "").trim(),
    city: (city || "").trim(),
    state: STATE_NAMES[stateAbbr] || stateAbbr,
    stateAbbr,
    types,
    description: "",
    insurance,
    phone: (phone || intake1 || "Call for information").trim(),
    website: "",
    latitude: 0,
    longitude: 0,
    featured: false,
    samhsa_verified: true,
    curated: false
  };
}

async function downloadXlsx() {
  console.log(`Downloading SAMHSA dataset from:\n  ${SAMHSA_XLSX_URL}`);
  const resp = await fetch(SAMHSA_XLSX_URL);
  if (!resp.ok) throw new Error(`Download failed: HTTP ${resp.status}`);

  const buffer = Buffer.from(await resp.arrayBuffer());
  fs.writeFileSync(TEMP_XLSX, buffer);
  console.log(`  Downloaded ${(buffer.length / 1024 / 1024).toFixed(2)} MB`);
  return TEMP_XLSX;
}

function parseXlsx(filePath) {
  let openpyxl;
  try {
    // Use xlsx package (pure JS, no native deps)
    const XLSX = require("xlsx");
    const wb = XLSX.readFile(filePath);
    const ws = wb.Sheets["Facilities List"];
    const rows = XLSX.utils.sheet_to_json(ws, { header: 1 });
    console.log(`  Parsed ${rows.length - 1} rows from 'Facilities List' sheet`);
    return rows.slice(1); // Skip header
  } catch (e) {
    if (e.code === "MODULE_NOT_FOUND") {
      console.error("ERROR: 'xlsx' package not installed. Run: npm install xlsx");
      process.exit(1);
    }
    throw e;
  }
}

function mergeWithExisting(newFacilities, existingFacilities) {
  const existingMap = new Map();
  for (const f of existingFacilities) {
    const key = `${(f.name || "").toLowerCase()}|${(f.city || "").toLowerCase()}|${(f.stateAbbr || "").toUpperCase()}`;
    existingMap.set(key, f);
  }

  const merged = [];
  let preserved = 0, added = 0;

  for (const fac of newFacilities) {
    const key = `${fac.name.toLowerCase()}|${fac.city.toLowerCase()}|${fac.stateAbbr}`;
    const existing = existingMap.get(key);

    if (existing) {
      fac.description = existing.description || fac.description;
      fac.website = existing.website || fac.website;
      fac.phone = (existing.phone && existing.phone !== "Call for information") ? existing.phone : fac.phone;
      fac.featured = existing.featured;
      fac.curated = existing.curated;
      fac.latitude = existing.latitude || fac.latitude;
      fac.longitude = existing.longitude || fac.longitude;
      preserved++;
    } else {
      added++;
    }
    merged.push(fac);
  }

  console.log(`  Merge: ${preserved} enriched records preserved, ${added} new facilities`);
  return merged;
}

function dedup(facilities) {
  const seen = new Map();
  for (const f of facilities) {
    const key = `${f.name.toLowerCase()}|${f.city.toLowerCase()}|${f.stateAbbr}`;
    if (!seen.has(key)) seen.set(key, f);
  }
  const deduped = [...seen.values()];
  if (deduped.length < facilities.length) {
    console.log(`  Dedup: removed ${facilities.length - deduped.length} duplicates`);
  }
  return deduped;
}

async function main() {
  console.log("=== GTH SAMHSA Data Refresh (Excel Download) ===");
  console.log(`Date: ${new Date().toISOString()}\n`);

  // Load existing data
  let existing = [];
  if (fs.existsSync(OUTPUT_FILE)) {
    existing = JSON.parse(fs.readFileSync(OUTPUT_FILE, "utf-8"));
    console.log(`Loaded ${existing.length} existing facilities`);
  }

  // Download SAMHSA Excel
  const xlsxPath = await downloadXlsx();

  // Parse Excel
  console.log("\nParsing SAMHSA data...");
  const rows = parseXlsx(xlsxPath);

  // Transform
  console.log("\nTransforming to GTH schema...");
  const transformed = rows.map(transformRow).filter(Boolean);
  console.log(`  ${transformed.length} valid facilities`);

  // Merge with existing enrichment
  console.log("\nMerging with existing enrichment data...");
  const merged = mergeWithExisting(transformed, existing);
  const final = dedup(merged);

  // Validate
  const jsonStr = JSON.stringify(final);
  const fileSize = Buffer.byteLength(jsonStr, "utf-8");
  console.log(`\nFinal: ${final.length} facilities, ${(fileSize / 1024 / 1024).toFixed(2)} MB`);

  if (final.length < 10000) {
    console.error(`WARNING: Only ${final.length} facilities (expected ~12,000+)`);
  }
  if (fileSize > MAX_FILE_SIZE) {
    console.error(`ERROR: File size exceeds ${MAX_FILE_SIZE / 1024 / 1024} MB limit!`);
    process.exit(1);
  }

  // Write
  fs.writeFileSync(OUTPUT_FILE, jsonStr);
  console.log(`\nSaved to ${OUTPUT_FILE}`);

  // Cleanup temp file
  fs.unlinkSync(TEMP_XLSX);

  // Stats
  const stateCounts = {};
  for (const f of final) stateCounts[f.stateAbbr] = (stateCounts[f.stateAbbr] || 0) + 1;
  const topStates = Object.entries(stateCounts).sort((a,b) => b[1] - a[1]).slice(0, 10);
  console.log(`\nTop 10 states: ${topStates.map(([s,c]) => `${s}:${c}`).join(", ")}`);
  console.log("\n=== Refresh complete ===");
}

main().catch(err => {
  console.error("FATAL:", err.message);
  process.exit(1);
});
