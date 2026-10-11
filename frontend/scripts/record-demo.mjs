// Record the demo walkthrough as a video against a running stack.
// Usage: BASE=http://localhost:8080/ node scripts/record-demo.mjs ../docs/demo
import { chromium } from "@playwright/test";
import { mkdirSync, readdirSync, renameSync } from "node:fs";
import { join } from "node:path";

const out = process.argv[2] ?? "../docs/demo";
const base = process.env.BASE ?? "http://localhost:8080/";
mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: out, size: { width: 1440, height: 900 } } });
const p = await ctx.newPage();
const pause = (ms) => p.waitForTimeout(ms);
const scrollTo = async (text) => { await p.getByText(text).first().scrollIntoViewIfNeeded(); await pause(2200); };

await p.goto(base);
await pause(1500);
await p.getByRole("button", { name: /Reset scenario & investigate/ }).first().click();
await p.waitForURL(/investigation/);
await p.locator(".stage.completed").nth(4).waitFor({ timeout: 60_000 });
await pause(2500);
await p.getByRole("button", { name: "Incident, as known then" }).click();
await pause(2500);
await p.getByRole("button", { name: "Now", exact: true }).click();
await pause(1500);
await p.locator("nav").getByRole("button", { name: "Story mode" }).click();
await pause(2000);
for (const t of ["Disabling the account does not contain it", "The hidden path", "The Price of Certainty",
  "Don't let the attacker write your plan", "The AI proposes, the graph disposes", "Don't trust us"]) await scrollTo(t);
await p.getByRole("button", { name: "Verify the k=0 certificate now" }).click();
await pause(3000);
await p.locator("nav").getByRole("button", { name: "Containment" }).click();
await pause(2000);
await scrollTo("Model advisor — the AI proposes, the graph disposes");
await p.locator("nav").getByRole("button", { name: "Company Brain" }).click();
await pause(1000);
await p.getByRole("button", { name: /Compare: as known then/ }).click();
await pause(3500);
await ctx.close();
await browser.close();
const vid = readdirSync(out).filter((f) => f.endsWith(".webm")).sort().pop();
if (vid) renameSync(join(out, vid), join(out, "ghosttrace-demo.webm"));
console.log("wrote", join(out, "ghosttrace-demo.webm"));
