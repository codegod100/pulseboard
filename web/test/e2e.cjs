// Browser test for the Qt web client against test/mock_server.py.
//   BASE=http://127.0.0.1:PORT node web/test/e2e.cjs   (SHOTS=dir for screenshots)
//
// The app draws into a canvas, so there is no DOM to query: the test reads the
// app's state through the pbSnapshot()/pbCall() hooks main.cpp exports, and
// drives the real UI with the mouse and keyboard where the layout is fixed.
const { chromium } = require("playwright");
const assert = require("assert");

const BASE = process.env.BASE;
const SHOTS = process.env.SHOTS;

(async () => {
  const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 800 } });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: BASE });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  const step = async (name, fn) => {
    try { await fn(); console.log("ok  ", name); }
    catch (e) { console.log("FAIL", name, "\n", e.message); process.exitCode = 1; }
  };
  const state = () => page.evaluate(() => JSON.parse(window.pulseboard.pbSnapshot()));
  const call = (m, arg) => page.evaluate(([m, arg]) => window.pulseboard.pbCall(m, arg), [m, arg ?? null]);
  const until = async (pred, what, ms = 8000) => {
    const end = Date.now() + ms;
    let s;
    while (Date.now() < end) {
      s = await state();
      if (pred(s)) return s;
      await page.waitForTimeout(100);
    }
    throw new Error("timed out waiting for " + what + "\n" + JSON.stringify(s).slice(0, 600));
  };
  const settled = (s) => s.listState === 1 && !s.refreshing;
  const shot = async (name) => { if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` }); };

  await page.goto(BASE + "/");
  await page.waitForFunction(() => window.pulseboard?.pbSnapshot, null, { timeout: 60000 });

  await step("page load fetches feeds and marks new articles with the red line", async () => {
    const s = await until((s) => settled(s) && s.articles[0]?.title === "Fresh story 1", "the refresh on load");
    assert.strictEqual(s.articles[1].newLine, true);
    assert.strictEqual(s.articles[0].newLine, false);
    assert.strictEqual(s.toast, "", "quiet refresh should not toast");
    assert.ok(s.unread > 0);
  });
  await page.waitForTimeout(400);
  await shot("desktop");

  await step("previews are plain text, and times are relative", async () => {
    const s = await state();
    assert.strictEqual(s.articles[0].preview, "Summary of Fresh story 1 & more");
    assert.strictEqual(s.articles[0].ago, "now");
    assert.strictEqual(s.articles[0].feedTitle, "Beta Blog");
  });

  await step("a row without an http(s) link says so instead of opening", async () => {
    const s = await state();
    const i = s.articles.findIndex((a) => a.title === "Broken link story");
    assert.strictEqual(s.articles[i].hasLink, false);
    await call("open", i);
    await until((s) => s.toast === "This article does not have a valid link.", "the no-link toast");
  });

  await step("the row's check button marks it read, and the count follows", async () => {
    const before = await state();
    // first row's button: 10px from the right edge, centred on the row
    await page.mouse.click(1200 - 10 - 18, 56 + 12 + 36 + 12 + 1 + 50);
    const s = await until((s) => s.articles[0].read, "row 0 read");
    assert.strictEqual(s.unread, before.unread - 1);
    await call("toggleRead", 0);
    await until((s) => !s.articles[0].read && s.unread === before.unread, "row 0 unread again");
  });

  await step("typing in the search box and pressing Enter searches", async () => {
    await page.mouse.click(200, 56 + 12 + 18);
    await page.keyboard.type("Old story 3");
    await page.keyboard.press("Enter");
    const s = await until((s) => s.search === "Old story 3" && settled(s), "the search");
    assert.deepStrictEqual(s.articles.map((a) => a.title), ["Old story 3"]);
    await shot("search");
    await page.keyboard.press("Escape");
    await until((s) => s.search === "" && settled(s) && s.articles.length > 1, "the search cleared");
  });

  await step("status tabs", async () => {
    await call("setStatus", 1);
    let s = await until((s) => s.status === 1 && settled(s), "All");
    const all = s.articles.length;
    await call("setStatus", 2);
    s = await until((s) => s.status === 2 && settled(s), "Read");
    assert.ok(s.articles.length < all);
    await call("setStatus", 0);
    await until((s) => s.status === 0 && settled(s), "Unread");
  });

  await step("picking a feed scopes the list and marking it read clears its count", async () => {
    let s = await state();
    const alpha = s.feeds.findIndex((f) => f.title === "Alpha News");
    await call("select", alpha);
    s = await until((s) => s.selected === alpha && settled(s), "Alpha selected");
    assert.ok(s.articles.length > 0 && s.articles.every((a) => a.feedTitle === "Alpha News"));
    await page.waitForTimeout(300);
    await shot("feed");
    // the top bar's "Mark all read", then Enter in the dialog
    await page.mouse.click(1200 - 8 - 36 - 2 - 18, 28);
    await page.waitForTimeout(300);
    await shot("mark-all-dialog");
    await page.keyboard.press("Enter");
    s = await until((s) => settled(s) && s.feeds[alpha].unread === 0 && s.articles.length === 0, "Alpha marked read");
    await call("select", -1);
    await until((s) => s.selected === -1 && settled(s), "back to everything");
  });

  await step("the RSS button opens Manage feeds", async () => {
    await page.mouse.click(1200 - 8 - 3 * 36 - 4 + 18, 28);
    await until((s) => s.managing, "manage open");
    await page.waitForTimeout(400);
    await shot("manage");
  });

  await step("adding a feed: errors toast, success lists it", async () => {
    await call("addFeed", "not a url");
    await until((s) => s.toast === "Not a feed URL.", "the add error");
    const n = (await state()).feeds.length;
    await call("addFeed", "https://g.example/feed");
    await until((s) => s.toast === "Feed added" && s.feeds.length === n + 1, "the new feed");
  });

  await step("editing a feed to a failing URL saves it and says why", async () => {
    let s = await state();
    const g = s.feeds.findIndex((f) => f.url === "https://g.example/feed");
    await call("editFeed", [g, "Gee", "https://g.example/fail", "news"]);
    s = await until((s) => s.toast.startsWith("Saved, but the feed failed:"), "the edit toast");
    const f = s.feeds.find((f) => f.url === "https://g.example/fail");
    assert.strictEqual(f.title, "Gee");
    assert.ok(f.error.includes("HTTP 403"));
    await call("editFeed", [s.feeds.indexOf(f), "Gee", "https://g.example/feed", "news"]);
    await until((s) => s.toast === "Feed updated, 2 new", "the second edit");
  });

  await step("importing and exporting OPML", async () => {
    await call("importOpml", "<opml version='2.0'><body><outline xmlUrl='https://h.example/feed'/></body></opml>");
    await until((s) => s.toast === "1 feed(s) added", "the import toast");
    await call("exportOpml");
    await until((s) => s.toast === "OPML backup copied to clipboard", "the export toast");
    const clip = await page.evaluate(() => navigator.clipboard.readText().catch(() => ""));
    assert.ok(clip.includes("<opml"), "clipboard holds the OPML");
  });

  await step("removing a feed", async () => {
    const s = await state();
    const g = s.feeds.findIndex((f) => f.url === "https://g.example/feed");
    await call("removeFeed", g);
    await until((s) => s.toast === "Feed removed" && !s.feeds.some((f) => f.url === "https://g.example/feed"), "the removal");
    await call("closeManage");
    await until((s) => !s.managing, "manage closed");
  });

  await step("phone width", async () => {
    await page.setViewportSize({ width: 390, height: 780 });
    await page.waitForTimeout(600);
    await shot("phone");
  });

  await step("a lost session goes to the sign-in page", async () => {
    await page.evaluate(() => fetch("/__signout"));
    await call("refresh");
    await page.waitForURL(/\/auth\/login$/, { timeout: 8000 });
  });

  await step("no errors in the console", async () => {
    assert.deepStrictEqual(errors.filter((e) => !/favicon|Failed to load resource/.test(e)), []);
  });

  await browser.close();
})();
