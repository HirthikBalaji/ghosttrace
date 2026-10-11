import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function axe(page: import("@playwright/test").Page, name: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  const serious = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${name}: ${v.id} (${v.nodes.length})`)).toEqual([]);
}

test("full demo flow: seed → investigate → plan → verify → brain → memory", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("SYNTHETIC DEMO")).toBeVisible();
  await axe(page, "command");
  await page.getByRole("button", { name: /Reset scenario & investigate/ }).first().click();
  await page.waitForURL(/investigation/);
  await expect(page.locator(".stage.completed")).toHaveCount(5, { timeout: 60_000 });
  await expect(page.getByText("CONFIRMED").first()).toBeVisible();
  // table fallback lists edges with class text (not color alone)
  await page.getByRole("button", { name: "Table", exact: true }).click();
  await expect(page.getByRole("cell", { name: /LATENT/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Incident, as known then" }).click();
  await axe(page, "investigation");

  await page.locator("nav").getByRole("button", { name: "Hypotheses" }).click();
  await expect(page.getByText("Stale guidance")).toBeVisible();
  await axe(page, "hypotheses");

  await page.locator("nav").getByRole("button", { name: "Containment" }).click();
  await expect(page.getByText("B0: disable the alerted account only")).toBeVisible();
  await expect(page.getByText("not contained").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Select k=1 plan/ })).toBeVisible();
  await page.getByRole("button", { name: /Select k=1 plan/ }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText("requires human scrutiny")).toBeVisible();
  await expect(page.getByText(/only under conservative_defense/)).toBeVisible();
  await axe(page, "containment");

  // model advisor: the AI proposes, the graph disposes
  await expect(page.getByText("Model advisor — the AI proposes, the graph disposes")).toBeVisible();
  await expect(page.getByText("✕ rejected").first()).toBeVisible();
  await expect(page.getByText("✔ accepted").first()).toBeVisible();
  // human approval of the k=1 plan requires acknowledging the scrutiny-flagged action
  const approve = page.getByRole("button", { name: "Approve plan" });
  await expect(approve).toBeDisabled();
  await page.getByRole("checkbox", { name: /independently checked the scrutiny-flagged/ }).check();
  await page.getByLabel("Decision note").fill("e2e: checked shared-config access logs");
  await approve.click();
  await expect(page.getByRole("status").filter({ hasText: "Approved" })).toContainText("no executor");
  await page.getByRole("button", { name: /Open certificate/ }).first().click();
  await page.getByRole("button", { name: /Verify with independent verifier/ }).click();
  await expect(page.getByRole("status")).toContainText("ACCEPTED");
  await axe(page, "certificate");

  await page.locator("nav").getByRole("button", { name: "Story mode" }).click();
  await expect(page.getByRole("heading", { name: /Disabling the account does not contain it/ })).toBeVisible();
  await page.getByRole("button", { name: "Verify the k=0 certificate now" }).click();
  await expect(page.getByRole("status")).toContainText("ACCEPTED by the independent verifier");
  await axe(page, "story");

  await page.locator("nav").getByRole("button", { name: "Company Brain" }).click();
  await page.getByRole("button", { name: /Compare: as known then/ }).click();
  await expect(page.getByText(/Payments team \(team:payments\) owned/)).toBeVisible();
  await expect(page.getByText(/Platform team \(team:platform\) owned/)).toBeVisible();
  await axe(page, "brain");

  await page.locator("nav").getByRole("button", { name: "Memory & audit" }).click();
  await expect(page.getByText("tainted").first()).toBeVisible();
  await expect(page.getByText(/investigator.*→.*evidence_verifier|investigator → evidence_verifier/).first()).toBeVisible();
  await axe(page, "memory");
});
