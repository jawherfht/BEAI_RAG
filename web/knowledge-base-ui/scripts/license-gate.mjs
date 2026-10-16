// Licence gate for production npm dependencies (ADR 0005).
// Allowed: MIT/Apache-2.0 and permissive licences. Exceptions are listed with the reason.
import { execFileSync } from "node:child_process";

const ALLOWED = new Set(["MIT", "Apache-2.0", "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "CC0-1.0", "BlueOak-1.0.0", "Python-2.0", "Unlicense"]);
const EXCEPTIONS = [
  // Next.js optional image optimiser; images.unoptimized=true and the Docker image strips it.
  { match: /^@img\/sharp-libvips-/, reason: "LGPL libvips via optional sharp: not used, not shipped" },
  // Browser-compatibility data used by browserslist at build time; CC-BY-4.0 (attribution, not NC).
  { match: /^caniuse-lite@/, reason: "CC-BY-4.0 data, attribution in THIRD_PARTY_NOTICES.md" },
];

const out = execFileSync("npx", ["license-checker", "--production", "--json", "--excludePrivatePackages"], { encoding: "utf8" });
const packages = JSON.parse(out);
const failures = [];
for (const [name, info] of Object.entries(packages)) {
  const licenses = String(info.licenses ?? "UNKNOWN").replace(/[()*]/g, "").split(/\s+(?:OR|AND)\s+/);
  if (licenses.some((l) => ALLOWED.has(l.trim()))) continue;
  const exception = EXCEPTIONS.find((e) => e.match.test(name));
  if (exception) {
    console.log(`exception: ${name} (${info.licenses}) — ${exception.reason}`);
    continue;
  }
  failures.push(`${name}: ${info.licenses}`);
}
if (failures.length) {
  console.error("Licence gate failed:\n  " + failures.join("\n  "));
  process.exit(1);
}
console.log(`licence gate OK (${Object.keys(packages).length} production packages)`);
