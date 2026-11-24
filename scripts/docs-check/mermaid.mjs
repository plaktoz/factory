const NM = process.env.MERMAID_NODE_MODULES || "node_modules";   // folder holding mermaid and jsdom
const { JSDOM } = await import(NM + "/jsdom/lib/api.js");
import fs from "node:fs";
const dom = new JSDOM("<!doctype html><body></body>");
globalThis.window = dom.window; globalThis.document = dom.window.document;
// Mermaid 11 reads these as bare globals, so a page with only window and document fails with "Element is not defined".
for (const k of ["Element", "HTMLElement", "SVGElement", "Node", "DOMParser"]) globalThis[k] = dom.window[k];
const mermaid = (await import(NM + "/mermaid/dist/mermaid.core.mjs")).default;
mermaid.initialize({ startOnLoad: false });
let bad = 0, n = 0;
for (const f of process.argv.slice(2)) {
  const t = fs.readFileSync(f, "utf8");
  for (const m of t.matchAll(/```mermaid\n([\s\S]*?)```/g)) {
    n++;
    try { await mermaid.parse(m[1]); console.log("ok   ", f.split("/").pop(), m[1].split("\n")[0]); }
    catch (e) { bad++; console.log("FAIL ", f.split("/").pop(), m[1].split("\n")[0], "::", String(e.message || e).split("\n")[0]); }
  }
}
console.log(n, "diagrams,", bad, "failed");
