// Browser check for a rendered decision page.
//   node check.mjs docs/decision-pages/<name>.html
// Needs puppeteer: `npm i puppeteer` in a scratch folder, then run with NODE_PATH pointing at its node_modules,
// or run this file from that folder. Exits 1 on any failed check.
import { createRequire } from "module";
import { pathToFileURL } from "url";
import { resolve } from "path";
const require = createRequire(process.env.PUPPETEER_FROM ? resolve(process.env.PUPPETEER_FROM, "x.js") : import.meta.url);
const puppeteer = require("puppeteer");

const file = process.argv[2];
if (!file) { console.error("usage: node check.mjs <page.html>"); process.exit(2); }
const fails = [];
const ok = (cond, msg) => { console.log((cond ? "PASS " : "FAIL ") + msg); if (!cond) fails.push(msg); };

const browser = await puppeteer.launch({ headless: "new", args: ["--no-sandbox"] });
const page = await browser.newPage();
const errors = [];
page.on("pageerror", e => errors.push(e.message));
page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
await page.setViewport({ width: 900, height: 1000 });
await page.goto(pathToFileURL(resolve(file)).href);
await page.evaluate(() => localStorage.clear());
await page.reload();

const cards = await page.$$eval("section.card:not(#out)", e => e.length);
const ids = await page.$$eval("section.card:not(#out) textarea[data-q]", e => e.map(x => x.dataset.q));
ok(cards > 0 && cards === ids.length, `${cards} decision cards rendered`);
ok((await page.$$eval("input[type=radio]:checked", e => e.length)) === cards, "one option preselected per card");

// a card in the user-side shape shows the question, Today and After, a preview, and "What you'll see" first on each option
const shape = await page.$$eval("section.card:not(#out)", cs => cs.map(c => ({
  ta: !!c.querySelector(".ta"), q: !!c.querySelector(".q"), pv: !!c.querySelector(".pv pre"),
  opts: [...c.querySelectorAll("label.opt")].filter(l => l.querySelector("input").value !== "unsure")
    .map(l => ({ see: !!l.querySelector(".see"), asks: !!l.querySelector(".asks"),
                 firstAfterName: (l.querySelector(".name") || {}).nextElementSibling })),
})));
const modern = shape.filter(s => s.ta);
if (modern.length) {
  ok(modern.every(s => s.q && s.pv), "each card shows its question and a preview");
  ok(modern.every(s => s.opts.every(o => o.see && o.asks)), "each option shows what you'll see and what it asks of you");
  const seeFirst = await page.$$eval("section.card:not(#out) label.opt", ls => ls.filter(l => l.querySelector(".see"))
    .every(l => { const n = l.querySelector(".see").previousElementSibling; return n && (n.classList.contains("name") || n.classList.contains("rec")); }));
  ok(seeFirst, "'What you'll see' is the first line under each option name");
  const how = await page.$("details.how");
  if (how) ok(await page.$eval("details.how", d => !d.open), "how it works starts folded");
}

// choose a non-recommended option on the first card and mark the last card unsure with a note
const first = ids[0], last = ids[ids.length - 1];
const alt = await page.$$eval(`input[name="${first}"]`, e => e.map(x => x.value).filter(v => v !== "unsure"));
const recFirst = await page.$eval(`input[name="${first}"]:checked`, e => e.value);
const other = alt.find(v => v !== recFirst);
const click = async sel => { await page.$eval(sel, e => e.scrollIntoView({ block: "center" })); await page.click(sel); };
await click(`input[name="${first}"][value="${other}"]`);
await click(`input[name="${last}"][value="unsure"]`);
await page.$eval(`textarea[data-q="${last}"]`, e => e.scrollIntoView({ block: "center" }));
await page.type(`textarea[data-q="${last}"]`, "check-question");
await page.click("#gen");
const out = await page.$eval("#prompt", e => e.value);
ok(await page.$eval("#out", e => getComputedStyle(e).display !== "none"), "prompt panel is shown");
ok(new RegExp(`^${first} .*\\[${other}\\] \\(not the recommendation\\)`, "m").test(out), "changed choice appears as 'not the recommendation'");
ok(new RegExp(`^${last} .*NOT SURE\\. Question: check-question`, "m").test(out), "unsure card carries its question");
ok((out.match(/\(recommended\)/g) || []).length === cards - 2, "all other cards stay recommended");

await page.reload();
ok((await page.$eval(`input[name="${first}"]:checked`, e => e.value)) === other, "choice survives a reload");
ok((await page.$eval(`textarea[data-q="${last}"]`, e => e.value)) === "check-question", "note survives a reload");

await page.setViewport({ width: 390, height: 900 });
ok(!(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)), "no horizontal scroll at 390px");
await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "dark" }]);
ok(await page.evaluate(() => getComputedStyle(document.body).backgroundColor !== "rgb(247, 247, 245)"), "dark mode changes the background");

await click('#reset').catch(() => {});
ok(errors.length === 0, "no console or page errors" + (errors.length ? ": " + errors[0] : ""));
await browser.close();
console.log(fails.length ? `\n${fails.length} CHECK(S) FAILED` : "\nALL CHECKS PASSED");
process.exit(fails.length ? 1 : 0);
