// Browser test for the web client against test/mock_server.py.
//   node web/test/e2e.cjs   (BASE=http://127.0.0.1:PORT, SHOTS=dir for screenshots)
const { chromium } = require("playwright");
const assert = require("assert");

const BASE = process.env.BASE;
const SHOTS = process.env.SHOTS;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  const step = async (name, fn) => {
    try { await fn(); console.log("ok  ", name); }
    catch (e) { console.log("FAIL", name, "\n", e.message); process.exitCode = 1; }
  };
  const titles = () => page.$$eval(".article h3", (hs) => hs.map((h) => h.textContent));
  const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };

  await page.goto(BASE + "/");

  await step("sidebar lists all feeds and each feed", async () => {
    await page.waitForSelector(".feed");
    const feeds = await page.$$eval(".feed .feed-title", (xs) => xs.map((x) => x.textContent));
    assert.deepStrictEqual(feeds, ["All feeds", "Alpha News", "Beta Blog"]);
  });

  await step("page load fetches feeds and marks new articles with the red line", async () => {
    await page.waitForFunction(() => document.querySelector(".article h3")?.textContent === "Fresh story 1");
    const order = await page.$$eval(".articles > li", (xs) => xs.map((x) => x.className));
    assert.strictEqual(order[0], "article");
    assert.strictEqual(order[1], "new-line");
    assert.strictEqual(await page.locator(".toast").count(), 0, "quiet refresh should not toast");
  });
  await shot("desktop");

  await step("rows are real links that open in a new tab", async () => {
    const a = page.locator(".article-link").first();
    assert.strictEqual(await a.getAttribute("href"), "https://example.com/7");
    assert.strictEqual(await a.getAttribute("target"), "_blank");
  });

  await step("previews are plain text, and times are relative", async () => {
    const p = await page.locator(".article p").first().textContent();
    assert.strictEqual(p, "Summary of Fresh story 1 & more");
    assert.strictEqual(await page.locator(".article time").first().textContent(), "now");
  });

  await step("opening an article marks it read", async () => {
    await page.route("https://example.com/**", (r) => r.fulfill({ body: "article" }));
    const [popup] = await Promise.all([ctx.waitForEvent("page"), page.locator(".article-link").first().click()]);
    await popup.close();
    await page.waitForSelector(".article.read");
    assert.strictEqual(await page.locator(".count.all").textContent(), "6");
  });

  await step("the check button toggles read", async () => {
    const row = page.locator(".article").nth(1);
    await row.locator(".btn").click();
    await page.waitForFunction(() => document.querySelectorAll(".article.read").length === 2);
    assert.strictEqual(await page.locator(".count.all").textContent(), "5");
    await row.locator(".btn").click();
    await page.waitForFunction(() => document.querySelectorAll(".article.read").length === 1);
  });

  await step("a row without a valid link says so", async () => {
    await page.locator(".article", { hasText: "Broken link story" }).locator(".article-link").click();
    await page.waitForSelector(".toast");
    assert.match(await page.locator(".toast").textContent(), /valid link/);
  });

  await step("choosing a feed scopes the list and the title", async () => {
    await page.locator(".feed", { hasText: "Alpha News" }).click();
    await page.waitForFunction(() => document.querySelector(".topbar h1").textContent === "Alpha News");
    await page.waitForFunction(() => [...document.querySelectorAll(".article .source")].every((s) => s.textContent === "Alpha News"));
    assert.strictEqual(await page.locator(".new-line").count(), 0);
  });

  await step("status tabs filter", async () => {
    await page.getByRole("tab", { name: "Read", exact: true }).click();
    await page.waitForFunction(() => document.querySelector(".state")?.textContent === "Nothing here.");
    await page.locator(".tab", { hasText: "All" }).click();
    await page.waitForSelector(".article");
  });

  await step("search spans everything", async () => {
    await page.locator(".search input").fill("old story 2");
    await page.locator(".search input").press("Enter");
    await page.waitForFunction(() => { const t = [...document.querySelectorAll(".article h3")].map((h) => h.textContent); return t.length === 1 && t[0] === "Old story 2"; });
    assert.strictEqual(await page.locator(".tabs-list").count(), 0);
    await page.locator(".search .btn").click();
    await page.waitForSelector(".tabs-list");
  });

  await step("refresh button fetches, toasts, and draws the line", async () => {
    await page.locator(".feed", { hasText: "All feeds" }).click();
    await page.locator(".tab", { hasText: "Unread" }).click();
    await page.waitForFunction(() => document.querySelector(".article h3")?.textContent === "Old story 5" || document.querySelector(".article h3")?.textContent === "Broken link story");
    await page.locator('[aria-label="Refresh"]').click();
    await page.waitForFunction(() => document.querySelector(".article h3")?.textContent === "Fresh story 2");
    await page.waitForSelector(".new-line");
    await page.waitForFunction(() => document.querySelector(".toast")?.textContent === "1 new");
  });

  await step("mark all read asks first", async () => {
    await page.locator('[aria-label="Mark all read"]').click();
    await page.waitForSelector(".dialog");
    await page.locator(".dialog .btn", { hasText: "Mark read" }).click();
    await page.waitForFunction(() => document.querySelector(".state")?.textContent === "Nothing here.");
    assert.strictEqual(await page.locator(".count").count(), 0);
  });

  await step("manage feeds: add, filter, remove", async () => {
    await page.locator('.topbar [aria-label="Manage feeds"]').click();
    await page.waitForSelector(".manage");
    await page.locator('.manage input[type="url"]').fill("https://c.example/atom");
    await page.locator(".manage .btn", { hasText: "Add" }).click();
    await page.waitForFunction(() => document.querySelectorAll(".subs li").length === 3);
    await page.locator('.manage input[type="search"]').fill("beta");
    await page.waitForFunction(() => document.querySelectorAll(".subs li").length === 1);
    await page.locator('.manage input[type="search"]').fill("");
    await shot("manage");
    await page.locator(".subs li", { hasText: "Gamma" }).locator(".btn").click();
    await page.locator(".dialog .btn", { hasText: "Remove" }).click();
    await page.waitForFunction(() => document.querySelectorAll(".subs li").length === 2);
  });

  await step("OPML import and export", async () => {
    await ctx.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.locator(".btn", { hasText: "Import OPML" }).click();
    await page.locator("textarea").fill("<opml/>");
    await page.locator(".dialog .btn", { hasText: "Import" }).click();
    await page.waitForFunction(() => document.querySelector(".toast")?.textContent === "1 feed(s) added");
    await page.locator(".btn", { hasText: "Copy OPML backup" }).click();
    await page.waitForFunction(() => document.querySelector(".toast")?.textContent === "OPML backup copied to clipboard");
    assert.match(await page.evaluate(() => navigator.clipboard.readText()), /<opml/);
    await page.locator('[aria-label="Back"]').click();
    await page.waitForSelector(".reader");
  });

  await step("narrow screens put the feeds in a drawer", async () => {
    await page.setViewportSize({ width: 390, height: 800 });
    await page.waitForTimeout(300);
    assert.ok(!(await page.locator(".sidebar").evaluate((n) => n.getBoundingClientRect().right > 0)));
    await page.locator('[aria-label="Feeds"]').click();
    await page.waitForTimeout(300);
    await shot("mobile-drawer");
    await page.locator(".feed", { hasText: "Beta Blog" }).click();
    await page.waitForFunction(() => !document.querySelector(".sidebar.open"));
    await page.waitForTimeout(300);
    await shot("mobile");
  });

  await step("a lost session goes to sign in", async () => {
    await page.evaluate(() => fetch("/__signout"));
    await page.locator('[aria-label="Refresh"]').click();
    await page.waitForURL("**/auth/login");
  });

  await step("no errors in the console", async () => {
    assert.deepStrictEqual(errors.filter((e) => !/401/.test(e)), []);
  });

  await browser.close();
})();
