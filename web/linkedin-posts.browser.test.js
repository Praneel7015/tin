import assert from "node:assert/strict";
import test from "node:test";
import {chromium} from "playwright";

const accounts = [
  {id: "a1", urn: "urn:li:person:AbC123", kind: "personal", name: "Sam Founder"},
  {id: "a2", urn: "urn:li:organization:42", kind: "organization", name: "Example Co"},
];
const initial = {
  schema_version: "tin.social.linkedin_draft.v1",
  posts: [{id: "p1", text: "We shipped the thing.", target: "", readiness: "ready", support: [], editor_notes: "", attachments: [], missing_assets: []}],
};

async function openReader(page, draft) {
  await page.route("http://localhost/linkedin-post-test", route => route.fulfill({body: "<!doctype html><html><body></body></html>", contentType: "text/html"}));
  await page.goto("http://localhost/linkedin-post-test");
  await page.addStyleTag({path: "src/tin_lite/static/app.css"});
  await page.addStyleTag({path: "src/tin_lite/static/x-posts.css"});
  await page.addScriptTag({path: "src/tin_lite/static/markdown-viewer.js"});
  await page.addScriptTag({path: "src/tin_lite/static/x-posts.js"});
  await page.evaluate(({draft, accounts}) => {
    window.requests = [];
    window.saved = structuredClone(draft);
    window.revision = "a".repeat(40);
    window.mockApi = async (path, options = {}) => {
      const body = options.body && JSON.parse(options.body);
      requests.push({path, method: options.method || "GET", body});
      if (path.includes("/linkedin/drafts") && !options.method) return {path: "social/linkedin/drafts/d.json", revision, draft: structuredClone(saved), accounts};
      if (path.endsWith("/linkedin/drafts") && options.method === "PUT") {
        saved = structuredClone(body.draft); revision = "b".repeat(40);
        return {path: body.path, revision, draft: structuredClone(saved)};
      }
      if (path.endsWith("/linkedin/preview")) {
        const post = saved.posts.find(item => item.id === body.post_id);
        return {preview_token: "exact-token", text: post.text, account: accounts.find(item => item.urn === post.target), attachments: post.attachments, valid_until: "2026-10-30T00:00:00Z"};
      }
      if (path.endsWith("/linkedin/publish")) return {id: "delivery-id", run_id: "delivery-id", status: "pending"};
      throw new Error(`Unexpected ${path}`);
    };
    window.mockRawFetch = async (path, options = {}) => {
      requests.push({path, method: options.method || "GET", type: options.body?.type});
      if (options.method === "POST") return new Response(JSON.stringify({path: new URL(path, location.href).searchParams.get("path"), revision: "c".repeat(40)}));
      return new Response(new Blob(["image"], {type: "image/png"}));
    };
    TinLinkedInPosts.open({projectId: "project-one", runId: "run-one", path: "social/linkedin/drafts/d.json", supportsAltText: true, api: mockApi, rawFetch: mockRawFetch});
  }, {draft, accounts});
  await page.locator(".x-posts-card").first().waitFor();
}

test("LinkedIn reader picks who posts, previews the exact post and publishes through LinkedIn's routes", async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 760, height: 900}});
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await openReader(page, initial);
    assert.equal(await page.locator(".x-posts-reader").getAttribute("aria-label"), "LinkedIn post drafts");
    // Two connected accounts and no target yet: nothing says who posts until one is chosen.
    assert.equal(await page.locator(".x-posts-account").count(), 0);
    await page.getByRole("button", {name: "Edit post", exact: true}).click();
    const picker = page.locator('[data-x-target="0"]');
    assert.deepEqual(await picker.locator("option").allInnerTexts(), ["Choose an account", "Sam Founder · profile", "Example Co · page"]);
    assert.equal(await page.locator('[data-x-text="0"]').getAttribute("maxlength"), "3000");
    assert.equal(await page.locator('[data-x-upload="0"]').getAttribute("accept"), "image/png,image/jpeg");
    await picker.selectOption("urn:li:organization:42");
    assert.match(await page.locator(".x-posts-account").innerText(), /Posting as Example Co/);
    await page.locator('[data-x-action="preview"][data-post="0"]').click();
    await page.locator("[data-x-exact]").waitFor();
    assert.match(await page.locator(".x-posts-account").innerText(), /Posting as Example Co/);
    assert.equal(await page.locator("[data-x-exact]").getAttribute("aria-label"), "Exact LinkedIn preview");
    await page.locator('[data-x-action="publish"]').click();
    await page.getByText(/Follow its progress in Activity/).waitFor();
    const calls = await page.evaluate(() => requests.filter(item => item.method !== "GET"));
    assert.deepEqual(calls.map(item => item.path), [
      "/api/projects/project-one/linkedin/drafts",
      "/api/projects/project-one/linkedin/preview",
      "/api/projects/project-one/linkedin/publish",
    ]);
    assert.equal(calls[0].body.draft.posts[0].target, "urn:li:organization:42");
    assert.equal(calls[2].body.preview_token, "exact-token");
    assert.deepEqual(errors, []);
  } finally {await browser.close();}
});

test("LinkedIn reader uploads images to LinkedIn's media folder and refuses video and a 21st image", async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const twenty = Array.from({length: 20}, (_, n) => ({type: "image", path: `media/${n}.png`, alt_text: ""}));
    await openReader(page, {...initial, posts: [{...initial.posts[0], target: "urn:li:person:AbC123"}]});
    // With a chosen target the reader says who posts before any preview.
    assert.match(await page.locator(".x-posts-account").innerText(), /Posting as Sam Founder/);
    await page.getByRole("button", {name: "Edit post", exact: true}).click();
    await page.locator('[data-x-upload="0"]').setInputFiles({name: "demo.mp4", mimeType: "video/mp4", buffer: Buffer.from([0, 0, 0, 24])});
    await page.getByText("Choose a PNG or JPEG image.").waitFor();
    await page.locator('[data-x-upload="0"]').setInputFiles({name: "shot.png", mimeType: "image/png", buffer: Buffer.from([137, 80, 78, 71])});
    await page.getByText(/Media uploaded to Files/).waitFor();
    const upload = await page.evaluate(() => requests.find(item => item.type === "image/png"));
    assert.match(decodeURIComponent(upload.path), /path=social\/linkedin\/media\/run-one\//);
    await page.locator('[data-x-alt="0:0"]').fill("The new dashboard");
    await openReader(page, {...initial, posts: [{...initial.posts[0], attachments: twenty}]});
    await page.getByRole("button", {name: "Edit post", exact: true}).click();
    await page.locator('[data-x-upload="0"]').setInputFiles({name: "more.png", mimeType: "image/png", buffer: Buffer.from([137, 80, 78, 71])});
    await page.getByText("Use up to 20 images per post.").waitFor();
  } finally {await browser.close();}
});

test("LinkedIn reader shows what a drafting run couldn't support, with or without posts", async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage();
    const gaps = [{angle: "A customer result", reason: "Add a publishable customer result."}];
    await openReader(page, {...initial, gaps});
    await page.locator('[data-x-action="notes"]').first().click();
    await page.getByText("More context needed").waitFor();
    assert.match(await page.locator(".x-posts-notes").innerText(), /Add a publishable customer result\./);
    await openReader(page, {...initial, posts: [], gaps});
    await page.getByText("This run wrote no posts.", {exact: false}).waitFor();
    assert.match(await page.locator(".x-posts-notes").innerText(), /Add a publishable customer result\./);
    assert.equal(await page.locator('[data-x-action="preview"]').count(), 0);
  } finally {await browser.close();}
});
