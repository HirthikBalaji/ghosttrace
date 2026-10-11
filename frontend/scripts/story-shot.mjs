// Screenshot of story mode: BASE=http://localhost:8080/ node scripts/story-shot.mjs <inv_id> <out.png>
import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await (await b.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
await p.goto(`${process.env.BASE ?? "http://localhost:8080/"}#/story/${process.argv[2]}`);
await p.getByRole("heading", { name: /Price of Certainty/ }).waitFor();
await p.waitForTimeout(800);
await p.screenshot({ path: process.argv[3], fullPage: true });
await b.close();
