const test = require("node:test");
const assert = require("node:assert");
const { formatCents, formatReport } = require("./format.js");

test("formats cents as dollars", () => {
  assert.strictEqual(formatCents(1599), "$15.99");
  assert.strictEqual(formatCents(5), "$0.05");
});

test("formats a report line", () => {
  assert.strictEqual(formatReport({ count: 3, total_cents: 1599 }), "3 orders, $15.99");
});
