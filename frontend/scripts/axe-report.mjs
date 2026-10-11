// Print axe violations for a page of the running preview: node scripts/axe-report.mjs [hash]
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "@playwright/test";

const b = await chromium.launch();
const p = await (await b.newContext()).newPage();
await p.goto("http://localhost:4173/" + (process.argv[2] ?? ""));
await p.waitForTimeout(2500);
const r = await new AxeBuilder({ page: p }).withTags(["wcag2a", "wcag2aa"]).analyze();
for (const v of r.violations)
  for (const n of v.nodes) console.log(v.id, v.impact, n.target.join(" "), (n.any[0]?.message ?? "").slice(0, 160));
await b.close();
