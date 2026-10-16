import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const KB1 = path.resolve(__dirname, "../../../eval/datasets/kb1_retail");
const FILES = ["returns-policy.pdf", "store-faq.md", "warranty.txt"].map((f) => path.join(KB1, f));

async function waitAllReady(page: Page, count: number, label = "Ready") {
  const pills = page.getByTestId("source-status");
  await expect(pills).toHaveCount(count, { timeout: 60_000 });
  await expect(async () => {
    const texts = await pills.allTextContents();
    expect(texts).toEqual(Array(count).fill(label));
  }).toPass({ timeout: 6 * 60_000, intervals: [2_000] });
}

test("screen B: upload, re-index, test the agent, save & continue", async ({ page }) => {
  const agentId = randomUUID();
  await page.goto(`/agents/${agentId}/knowledge-base?agentName=Acme%20Shoes`);

  await expect(page.getByRole("heading", { name: "B · Knowledge Base & RAG" })).toBeVisible();
  await expect(page.getByTestId("warning-banner")).toHaveText(/Answers only from uploaded sources/);
  await expect(page.getByText("Ground Acme Shoes's answers in your own documents.")).toBeVisible();
  await expect(page.getByTestId("chunk-size-value")).toHaveText("512 tokens");
  await expect(page.getByTestId("top-k")).toHaveText("4");

  // Upload 3 files and watch the status pills go to Ready.
  await page.getByTestId("file-input").setInputFiles(FILES);
  await expect(page.getByTestId("source-row")).toHaveCount(3);
  await waitAllReady(page, 3);
  await expect(page.getByTestId("sources-summary")).toHaveText("3 files, 0 URLs");

  // Move the chunk-size slider: settings are saved and every source is re-indexed.
  const slider = page.getByTestId("chunk-size");
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("chunk-size-value")).toHaveText("550 tokens");
  await expect(page.getByTestId("reindexing")).toBeVisible({ timeout: 30_000 });
  await waitAllReady(page, 3);
  await expect(page.getByTestId("reindexing")).toBeHidden();

  // Test this agent with the wireframe question.
  await page.getByTestId("test-question").fill("What's your return policy?");
  await page.getByTestId("ask").click();
  await expect(page.getByTestId("confidence")).toHaveText("high", { timeout: 120_000 });
  const answer = (await page.getByTestId("answer").textContent()) ?? "";
  expect(answer).toMatch(/30 days/i);
  expect(answer).toMatch(/unworn/i);
  expect(answer).toMatch(/receipt/i);
  const chip = page.getByTestId("source-chip").first();
  await expect(chip).toHaveText("returns-policy.pdf p.2");
  await chip.click();
  await expect(page.getByTestId("source-snippet")).toContainText("30 days, unworn, with receipt");
  await expect(page.getByTestId("latency")).toBeVisible();

  // Save & Continue -> Persona Builder shows the status chip.
  await page.getByTestId("save-continue").click();
  await expect(page).toHaveURL(new RegExp(`/agents/${agentId}/persona`));
  await expect(page.getByTestId("kb-status-chip")).toHaveText("Knowledge base: 3 files, RAG on");
});

test("screen B is translated (fr) and an unanswerable question uses the fallback", async ({ page }) => {
  const agentId = randomUUID();
  await page.goto(`/agents/${agentId}/knowledge-base?lang=fr`);
  await expect(page.getByRole("heading", { name: "B · Base de connaissances & RAG" })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(FILES[2]!);
  await waitAllReady(page, 1, "Prêt");
  await page.getByTestId("test-question").fill("What is the capital of Australia?");
  await page.getByTestId("ask").click();
  await expect(page.getByTestId("confidence")).toHaveText("faible", { timeout: 60_000 });
  await expect(page.getByTestId("source-chip")).toHaveCount(0);
});
