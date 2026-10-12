import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "apps/web/package.json"));
const { chromium } = require("@playwright/test");
const web = process.env.CASEQUARRY_E2E_WEB || "http://127.0.0.1:3000";
const email = process.env.CASEQUARRY_E2E_EMAIL;
const password = process.env.CASEQUARRY_E2E_PASSWORD;
const setupToken = process.env.CASEQUARRY_E2E_SETUP_TOKEN;
const fixtureRoot = process.env.CASEQUARRY_E2E_FIXTURES;
const artifactRoot = process.env.CASEQUARRY_E2E_ARTIFACTS || path.join(root, ".data/browser-e2e");
assert(email && password && fixtureRoot, "Set the private E2E account and fixture environment variables; credentials are never printed.");
await mkdir(artifactRoot, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1512, height: 982 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(30000);
const errors = [];
page.on("pageerror", error => errors.push(error.message));
let caseId;
const report = { checks: [], artifacts: [], synthetic_only: true };
const checked = label => { report.checks.push(label); console.log(`Passed: ${label}`); };
const responseFor = (route, matches = () => true) => page.waitForResponse(response => response.url().split("?")[0].endsWith(route) && response.request().method() === "POST" && matches(response.request()));
async function screenshot(name) {
  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
  await page.screenshot({ path: path.join(artifactRoot, name), fullPage: true });
  report.artifacts.push(name);
}

try {
  await page.goto(web + (setupToken ? "/setup" : "/login"));
  if (setupToken) {
    await page.getByLabel("Setup token", { exact: true }).fill(setupToken);
    await page.getByLabel("Firm or workspace name", { exact: true }).fill("Synthetic CaseQuarry Evaluation");
    await page.getByLabel("Your name", { exact: true }).fill("Synthetic Reviewer");
  }
  await page.getByLabel("Email address", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: setupToken ? "Create private workspace" : "Sign in", exact: true }).click();
  await page.waitForURL(/\/app$/);
  checked("authenticated workspace setup/login");

  await page.goto(web + "/app/matters/new");
  await page.getByLabel("Matter number", { exact: true }).fill("SYN-E2E-" + Date.now());
  await page.getByLabel("Matter title", { exact: true }).fill("Orion Holdings v Delta Freight · Synthetic");
  const caseResponse = responseFor("/api/v1/cases");
  await page.getByRole("button", { name: "Create matter", exact: true }).click();
  const created = await (await caseResponse).json();
  caseId = created.id;
  assert(caseId);
  await page.waitForURL(new RegExp(`/app/matters/${caseId}/overview`));
  checked("matter creation connected to API");

  await page.goto(web + `/app/matters/${caseId}/sources`);
  await page.getByRole("button", { name: "Import files", exact: true }).click();
  const files = [path.join(fixtureRoot, "example-eml/message-0000.eml"), path.join(fixtureRoot, "example-eml/message-0001.eml"), path.join(fixtureRoot, "documents/synthetic-0002.pdf")];
  await page.getByLabel("Choose evidence files", { exact: true }).setInputFiles(files);
  await page.getByLabel("New source label", { exact: true }).fill("Synthetic original EML and PDF");
  await page.getByLabel(/Custodian name/).fill("Synthetic Finance Team");
  const importResponse = responseFor(`/api/v1/cases/${caseId}/imports`);
  await page.getByRole("button", { name: "Import 3 files", exact: true }).click();
  const batch = await (await importResponse).json();
  for (let attempt = 0; attempt < 120; attempt++) {
    const response = await page.request.get(web + `/api/v1/cases/${caseId}/imports/${batch.batch_id}`);
    assert(response.ok(), "Authorized import status must succeed");
    const state = await response.json();
    if (["completed", "partial", "failed"].includes(state.state)) {
      assert.equal(state.state, "completed", "Supported EML/PDF import must complete without hidden failures");
      break;
    }
    assert(attempt < 119, "Import did not complete in the browser test time budget");
    await page.waitForTimeout(250);
  }
  checked("EML/PDF upload and durable import completion");

  await page.goto(web + `/app/matters/${caseId}/explorer`);
  await page.getByLabel("Search evidence", { exact: true }).fill('"payment approved"');
  const searchResponse = responseFor(`/api/v1/cases/${caseId}/search`, request => request.postDataJSON().query === '"payment approved"');
  await page.getByRole("button", { name: "Search", exact: true }).click();
  const search = await (await searchResponse).json();
  assert.equal(search.total_hits, 1);
  const groupResponse = responseFor(`/api/v1/cases/${caseId}/search`, request => request.postDataJSON().group_by === "sender");
  await page.getByLabel("Group evidence", { exact: true }).selectOption("sender");
  assert.equal((await (await groupResponse).json()).total_hits, 1);
  const sortResponse = responseFor(`/api/v1/cases/${caseId}/search`, request => request.postDataJSON().sort?.[0]?.order === "asc");
  await page.getByLabel("Sort evidence", { exact: true }).selectOption("sent_at:asc");
  assert.equal((await (await sortResponse).json()).total_hits, 1);
  await page.locator(".evidence-open").first().click();
  await page.getByRole("tab", { name: "Content", exact: true }).waitFor();
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await page.getByText("Original hash verified.", { exact: true }).waitFor();
  const itemId = search.items[0].evidence_id;
  checked("real phrase search, server group/sort and source verification");

  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Original", exact: true }).click();
  const original = await downloadEvent;
  const downloaded = path.join(artifactRoot, "synthetic-original.eml");
  await original.saveAs(downloaded);
  assert.equal(createHash("sha256").update(await readFile(downloaded)).digest("hex"), createHash("sha256").update(await readFile(files[0])).digest("hex"));
  checked("authorized original download preserves exact uploaded bytes");

  await page.getByRole("tab", { name: "Review", exact: true }).click();
  const reviewResponse = responseFor(`/api/v1/cases/${caseId}/evidence/${itemId}/reviews`);
  await page.getByRole("button", { name: "Responsive", exact: true }).click();
  assert((await reviewResponse).ok());
  await page.getByText("Review saved in the audit record.", { exact: true }).waitFor();
  await page.getByLabel("Comma-separated evidence tags", { exact: true }).fill("Financial, Synthetic verified");
  const tagsResponse = responseFor(`/api/v1/cases/${caseId}/evidence/${itemId}/reviews`);
  await page.getByRole("button", { name: "Save tags", exact: true }).click();
  assert((await tagsResponse).ok());
  await page.getByLabel("Evidence review note", { exact: true }).fill("Synthetic browser acceptance: source bytes verified.");
  await page.getByRole("button", { name: "Add note", exact: true }).click();
  await page.getByText("Note saved.", { exact: true }).waitFor();
  checked("human responsiveness, tags and note saved through API");
  await screenshot("explorer-synthetic.png");

  await page.goto(web + `/app/matters/${caseId}/reports`);
  await page.getByRole("combobox", { name: /^Export format/ }).selectOption("zip");
  await page.getByLabel("Purpose or reason", { exact: true }).fill("Synthetic end-to-end acceptance");
  await page.getByLabel("I have reviewed the scope and am authorized to export this evidence.", { exact: true }).check();
  const exportResponse = responseFor(`/api/v1/cases/${caseId}/exports`);
  await page.getByRole("button", { name: "Create export", exact: true }).click();
  assert.equal((await exportResponse).status(), 409, "Unreviewed native evidence must be held back");
  checked("native export refuses remaining unreviewed evidence");

  const fullScopeResponse = responseFor(`/api/v1/cases/${caseId}/search`, request => request.postDataJSON().query === "");
  await page.goto(web + `/app/matters/${caseId}/explorer`);
  assert.equal((await (await fullScopeResponse).json()).total_hits, 4);
  await page.getByLabel("Select all visible evidence", { exact: true }).check();
  await page.getByRole("button", { name: "Review selected", exact: true }).click();
  await page.getByRole("combobox", { name: /^Review decision/ }).selectOption("responsive");
  const bulkResponse = responseFor(`/api/v1/cases/${caseId}/reviews/bulk`);
  await page.getByRole("button", { name: "Save review decisions", exact: true }).click();
  assert((await bulkResponse).ok());
  await page.getByRole("dialog").waitFor({ state: "hidden" });
  checked("explicit human bulk review completes the native export scope");

  await page.goto(web + `/app/matters/${caseId}/reports`);
  await page.getByRole("combobox", { name: /^Export format/ }).selectOption("zip");
  await page.getByLabel("Purpose or reason", { exact: true }).fill("Synthetic reviewed native acceptance");
  await page.getByLabel("I have reviewed the scope and am authorized to export this evidence.", { exact: true }).check();
  const reviewedExportResponse = responseFor(`/api/v1/cases/${caseId}/exports`);
  await page.getByRole("button", { name: "Create export", exact: true }).click();
  assert((await reviewedExportResponse).ok());
  const exportedEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download", exact: true }).first().click();
  const exported = await exportedEvent;
  const packagePath = path.join(artifactRoot, "synthetic-export.zip");
  await exported.saveAs(packagePath);
  assert.equal((await readFile(packagePath)).subarray(0, 2).toString(), "PK");
  checked("explicit authorized export and manifest package download");

  await page.goto(web + `/app/matters/${caseId}/overview`);
  await page.getByRole("heading", { name: "Orion Holdings v Delta Freight · Synthetic", exact: true }).waitFor();
  await screenshot("overview-synthetic.png");
  await page.goto(web + `/app/matters/${caseId}/audit`);
  const auditResponse = responseFor(`/api/v1/cases/${caseId}/audit/verify`);
  await page.getByRole("button", { name: /Verify audit chain/ }).click();
  assert.equal((await (await auditResponse).json()).valid, true);
  await screenshot("audit-synthetic.png");
  checked("live overview and attributed audit view");
  assert.deepEqual(errors, [], "No browser runtime errors are permitted");
  report.status = "passed";
  report.case_id = caseId;
} catch (error) {
  report.status = "failed";
  report.error = error.message;
  await screenshot("failure-synthetic.png");
  throw error;
} finally {
  await writeFile(path.join(artifactRoot, "report.json"), JSON.stringify(report, null, 2));
  await browser.close();
}
