// Packaged dashboard with synthetic APIs. No live credentials or projects.
// People (Paper PEOPLE-A1, C1, C1b): a grid of everyone the project keeps, segments, the reason
// behind a score, a person beside the grid, and Forget confirmed in place.
import assert from "node:assert/strict";
import test from "node:test";
import { chromium } from "playwright";
import { openApp, serveApp } from "./app-fixture.js";

const title = page => page.locator("#main h1").first().evaluate(node => {
  const style = getComputedStyle(node);
  return {family: style.fontFamily, weight: style.fontWeight, size: style.fontSize, tracking: style.letterSpacing, leading: style.lineHeight};
});

test("People shows in the menu only where a workflow that finds people is offered", {timeout: 120000}, async () => {
  for (const engagers of [true, false]) {
    const {server, base} = await serveApp({engagers});
    const browser = await chromium.launch({headless: true});
    try {
      const {page, context, errors} = await openApp(browser, base, {url: "/system"});
      await page.locator(".system-header h1").waitFor();
      assert.equal(await page.locator('.nav-item[data-view="people"]').isVisible(), engagers);
      if (engagers) {
        await page.locator('.nav-item[data-view="people"]').click();
        await page.locator(".people-table").waitFor();
        assert.equal(new URL(page.url()).pathname, "/people");
      }
      assert.deepEqual(errors, []);
      await context.close();
    } finally {
      await browser.close();
      server.close();
    }
  }
});

test("People's title is set like System's", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const system = await openApp(browser, base, {url: "/system"});
    await system.page.locator(".system-header h1").waitFor();
    const expected = await title(system.page);
    await system.context.close();
    const {page, context, errors} = await openApp(browser, base, {url: "/people"});
    await page.locator(".people-table").waitFor();
    assert.equal(await page.locator("#main h1").textContent(), "People");
    assert.deepEqual(await title(page), expected);
    assert.equal(expected.weight, "700");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("the grid lists people best fit first, by segment, with the reason behind a score", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/people"});
    await page.locator(".people-table").waitFor();
    assert.equal(await page.locator('.nav-item[data-view="people"]').getAttribute("class"), "nav-item is-active");
    const names = () => page.locator(".people-table tbody td.is-name").allTextContents();
    assert.deepEqual(await names(), ["Maya Lindqvist", "Daniel Okafor", "Sofia Marchetti", "Lea Fischer", "Hannah Kim"]);
    assert.deepEqual(await page.locator(".people-sections .workflow-section").allTextContents(), ["All people 5", "ICP fit 3", "Not connected yet 3"]);
    // A score made under an older ICP file reads "old"; a person not scored shows a dash.
    assert.equal(await page.locator('td[data-fit="p-sofia"]').textContent(), "old0.66");
    assert.equal(await page.locator('td[data-fit="p-hannah"]').textContent(), "—");
    assert.equal(await page.locator(".people-pager code").textContent(), "1–5 of 5");

    await page.locator('td[data-fit="p-sofia"]').hover();
    const hover = page.locator(".people-hover.is-visible");
    await hover.waitFor();
    assert.match(await hover.innerText(), /no marketing lead[\s\S]*0\.66 · ICP 1 · oct 15[\s\S]*Scored before strategy\/ICP\.md changed\. The next run rescores it\./);

    await page.getByRole("tab", {name: "Not connected yet 3"}).click();
    assert.deepEqual(await names(), ["Daniel Okafor", "Lea Fischer", "Hannah Kim"]);
    await page.getByRole("tab", {name: "ICP fit 3"}).click();
    assert.deepEqual(await names(), ["Maya Lindqvist", "Daniel Okafor", "Sofia Marchetti"]);
    await page.getByRole("button", {name: "Name"}).click();
    assert.deepEqual(await names(), ["Daniel Okafor", "Maya Lindqvist", "Sofia Marchetti"]);
    await page.getByRole("tab", {name: "All people 5"}).click();
    await page.getByLabel("Search people").fill("patchbay");
    assert.deepEqual(await names(), ["Sofia Marchetti"]);
    await page.getByLabel("Search people").fill("nobody");
    assert.equal(await page.locator(".people-table tr.is-none").textContent(), "No one matches “nobody”.");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("a person opens beside a narrower grid, and the address keeps them", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/people"});
    await page.locator(".people-table").waitFor();
    assert.equal(await page.locator(".people-table th.is-headline").isVisible(), true);
    await page.getByRole("row", {name: "Maya Lindqvist"}).click();
    const panel = page.locator("#person-panel");
    await panel.getByRole("link", {name: "Open on LinkedIn"}).waitFor();
    assert.equal((await panel.boundingBox()).width, 420);
    assert.equal(await page.locator(".people-table th.is-headline").isVisible(), false);
    assert.equal(await page.locator(".people-table th.is-touch").isVisible(), false);
    assert.equal(new URL(page.url()).searchParams.get("person"), "p-maya");
    assert.match(await panel.locator(".person-section").first().innerText(), /Fields\s*3[\s\S]*ICP fit\s*0\.84\s*engagers · oct 15/);
    await panel.getByText("Reacted to your post with Insightful").waitFor();
    assert.equal(await panel.getByText("Reacted to a teammate’s post with Like").count(), 1);
    assert.equal(await panel.locator("a.person-event").first().getAttribute("target"), "_blank");
    assert.equal(await panel.locator("footer code").textContent(), "added oct 15 by engagers");
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);

    // A reload opens the same person; Escape in the panel closes it.
    await page.reload();
    await page.locator("#person-panel h2").getByText("Maya Lindqvist").waitFor();
    await page.locator("#person-panel").focus();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#person-panel").count(), 0);
    assert.equal(new URL(page.url()).searchParams.get("person"), null);
    assert.equal(await page.locator(".people-table th.is-headline").isVisible(), true);

    // Leaving People closes the person.
    await page.getByRole("row", {name: "Daniel Okafor"}).click();
    await page.locator('.nav-item[data-view="files"]').click();
    assert.equal(await page.locator("#person-panel").count(), 0);
    assert.equal(new URL(page.url()).searchParams.get("person"), null);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("Forget asks in place first, then removes the person", {timeout: 120000}, async () => {
  const {server, base, people} = await serveApp({engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/people", theme: "dark"});
    await page.getByRole("row", {name: "Lea Fischer"}).click();
    const panel = page.locator("#person-panel");
    await panel.getByRole("button", {name: "Forget this person"}).click();
    assert.match(await panel.locator("footer").innerText(), /Forget Lea Fischer\?\s*Tin deletes this person’s fields and timeline in Example Co and won’t add them again, even when they react to a later post\. The list in Files drops them at the next run\./);
    await panel.getByRole("button", {name: "Cancel"}).click();
    assert.equal(people.length, 5);
    await panel.getByRole("button", {name: "Forget this person"}).click();
    await panel.getByRole("button", {name: "Forget", exact: true}).click();
    await page.locator("#person-panel").waitFor({state: "detached"});
    assert.equal(people.some(item => item.id === "p-lea"), false);
    assert.equal(await page.getByRole("row", {name: "Lea Fischer"}).count(), 0);
    assert.equal(await page.locator(".toast").textContent(), "Forgot Lea Fischer.");
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("without people, People says how they arrive", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({people: [], engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/people"});
    const empty = page.locator(".people-body .decisions-empty");
    await empty.waitFor();
    assert.match(await empty.innerText(), /No people yet\.\s*When someone reacts to your LinkedIn posts, Tin adds them here/);
    assert.equal(await page.locator(".people-view .search-field").isVisible(), false);
    await empty.getByRole("button", {name: "Open System"}).click();
    await page.locator(".system-header h1").waitFor();
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});

test("on a phone the grid scrolls inside the page and the person fills the screen", {timeout: 120000}, async () => {
  const {server, base} = await serveApp({engagers: true});
  const browser = await chromium.launch({headless: true});
  try {
    const {page, context, errors} = await openApp(browser, base, {url: "/people", viewport: {width: 390, height: 800}});
    await page.locator(".people-table").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.getByRole("row", {name: "Maya Lindqvist"}).click();
    const panel = await page.locator("#person-panel").boundingBox();
    assert.equal(Math.round(panel.width), 390);
    assert.deepEqual(errors, []);
    await context.close();
  } finally {
    await browser.close();
    server.close();
  }
});
