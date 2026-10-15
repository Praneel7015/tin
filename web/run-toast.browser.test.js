// Packaged dashboard with synthetic APIs. No live credentials or projects.
// Starting a workflow names it the way the founder knows it, never by its catalog key.
import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { openApp, serveApp } from "./app-fixture.js";

test("a manual run's toast names the workflow, not its key", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({decisionCount: 0});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/system"});
    await page.getByRole("button", {name: "Draft an answer page"}).first().click();
    await page.getByRole("button", {name: "Manual run", exact: true}).click();
    // The toast element is always in the page; wait for this run's words in it.
    const toast = page.locator(".toast", {hasText: "started."});
    await toast.waitFor();
    assert.equal(await toast.textContent(), "Draft an answer page started.");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});
