// Frontend dependency-audit gate (M11 §7.2 / AC-11-1).
//
// npm retired its legacy audit endpoints (HTTP 410), which broke
// `pnpm audit`. This gate instead scans the pnpm lockfile with osv-scanner
// (OSV.dev — no npm endpoint) and enforces the SAME policy pnpm audit did:
//   "zero un-waived HIGH+ / CRITICAL advisories".
// Waivers remain the single source of truth in package.json
// (pnpm.auditConfig.ignoreGhsas), documented in
// docs/security/dependency-waivers.md. LOW/MODERATE are not gated, exactly as
// `pnpm audit --audit-level=high` behaved.
//
// Usage: node audit-gate.mjs <osv-scanner-json> <package.json>
import fs from "node:fs";

const [, , osvPath, pkgPath] = process.argv;
if (!osvPath || !pkgPath) {
  console.error("usage: audit-gate.mjs <osv.json> <package.json>");
  process.exit(2);
}

const osv = JSON.parse(fs.readFileSync(osvPath, "utf8"));
const waivers = new Set(
  JSON.parse(fs.readFileSync(pkgPath, "utf8")).pnpm?.auditConfig?.ignoreGhsas ?? [],
);

const GATED = new Set(["HIGH", "CRITICAL"]);
const offenders = [];
const matchedWaivers = new Set();

for (const result of osv.results ?? []) {
  for (const pkg of result.packages ?? []) {
    for (const vuln of pkg.vulnerabilities ?? []) {
      const severity = vuln.database_specific?.severity ?? "UNKNOWN";
      if (!GATED.has(severity)) continue;
      const ids = [vuln.id, ...(vuln.aliases ?? [])];
      const waived = ids.find((id) => waivers.has(id));
      if (waived) {
        matchedWaivers.add(waived);
        continue;
      }
      const ghsa = ids.find((id) => id.startsWith("GHSA")) ?? vuln.id;
      offenders.push(`${severity}  ${ghsa}  ${pkg.package.name}@${pkg.package.version}`);
    }
  }
}

if (offenders.length) {
  console.error(`\n✖ ${offenders.length} un-waived HIGH+/CRITICAL advisory(ies):\n`);
  for (const o of offenders) console.error("   " + o);
  console.error(
    "\nUpgrade the dependency, or add the GHSA to package.json " +
      "(pnpm.auditConfig.ignoreGhsas) with a justification in " +
      "docs/security/dependency-waivers.md.\n",
  );
  process.exit(1);
}

const stale = [...waivers].filter((w) => !matchedWaivers.has(w));
if (stale.length) {
  // Non-fatal: report waivers that no longer match any HIGH+ finding so they
  // can be pruned, but do not fail the build on cleanup debt.
  console.log(`note: ${stale.length} waiver(s) no longer match a HIGH+ finding: ${stale.join(", ")}`);
}
console.log("✓ osv-scanner: zero un-waived HIGH+/CRITICAL advisories.");
