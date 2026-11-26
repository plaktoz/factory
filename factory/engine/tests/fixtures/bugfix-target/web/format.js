// Turns a report from the API into the line the page prints.
function formatCents(cents) {
  const sign = cents < 0 ? "-" : "";
  const abs = Math.abs(cents);
  return `${sign}$${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, "0")}`;
}

function formatReport(report) {
  return `${report.count} orders, ${formatCents(report.total_cents)}`;
}

module.exports = { formatCents, formatReport };

if (require.main === module) {
  let input = "";
  process.stdin.on("data", (chunk) => (input += chunk));
  process.stdin.on("end", () => console.log(formatReport(JSON.parse(input))));
}
