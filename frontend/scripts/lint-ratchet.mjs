#!/usr/bin/env node
/*
 * Lint ratchet (Phase 1 Batch 2 — CI policy for BASELINE_FUNCTIONAL_AUDIT KF-9).
 *
 * `pnpm lint` (eslint --max-warnings 0) is RED on inherited debt: 19 errors,
 * 6 warnings. Blocking CI on that would either stall the project or pressure
 * people to blanket-suppress. Instead:
 *
 *   - the full eslint report is always printed (nothing is hidden);
 *   - CI FAILS if the error or warning count EXCEEDS .lint-baseline.json
 *     (i.e. a genuine regression / new violation);
 *   - when the real count drops below the baseline, CI PASSES but prints a
 *     reminder to lower the baseline — so the gate ratchets toward 0/0.
 *
 * Run: `node scripts/lint-ratchet.mjs`  (also `pnpm lint:ratchet`)
 */
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { createRequire } from "node:module";

const frontendDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const baseline = JSON.parse(
  readFileSync(join(frontendDir, ".lint-baseline.json"), "utf8"),
);

// Resolve eslint's own bin from node_modules so this works cross-platform
// without depending on a package-manager shim on PATH.
const require = createRequire(import.meta.url);
const eslintBin = join(
  dirname(require.resolve("eslint/package.json")),
  "bin",
  "eslint.js",
);

let raw = "";
try {
  raw = execFileSync(
    process.execPath,
    [eslintBin, ".", "--ext", "ts,tsx", "--format", "json"],
    { cwd: frontendDir, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"], maxBuffer: 32 * 1024 * 1024 },
  );
} catch (err) {
  // eslint exits non-zero when it finds problems; the JSON is still on stdout.
  raw = err.stdout?.toString() ?? "";
  if (!raw) {
    console.error("lint-ratchet: eslint produced no JSON output");
    process.exit(2);
  }
}

const results = JSON.parse(raw);
let errors = 0;
let warnings = 0;
const lines = [];
for (const file of results) {
  if (file.errorCount === 0 && file.warningCount === 0) continue;
  errors += file.errorCount;
  warnings += file.warningCount;
  for (const m of file.messages) {
    lines.push(
      `  ${file.filePath.replace(frontendDir + "/", "").replace(frontendDir + "\\", "")}:${m.line}:${m.column}  ${m.severity === 2 ? "error" : "warning"}  ${m.message}  ${m.ruleId ?? ""}`,
    );
  }
}

if (lines.length) {
  console.log("\nESLint findings:\n" + lines.join("\n") + "\n");
}
console.log(
  `lint-ratchet: ${errors} error(s), ${warnings} warning(s)  ` +
    `(baseline: <=${baseline.maxErrors} errors, <=${baseline.maxWarnings} warnings)`,
);

if (errors > baseline.maxErrors || warnings > baseline.maxWarnings) {
  console.error(
    `\n❌ Lint REGRESSION: exceeds the committed baseline. ` +
      `Fix the new finding(s) above, or (only if intentional) update .lint-baseline.json with justification.`,
  );
  process.exit(1);
}

if (errors < baseline.maxErrors || warnings < baseline.maxWarnings) {
  console.log(
    `\n🎯 Ratchet opportunity: lint debt dropped. Lower .lint-baseline.json to ` +
      `{ "maxErrors": ${errors}, "maxWarnings": ${warnings} } to lock in the gain.`,
  );
}

console.log("\n✅ Lint within baseline.");
