const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const flow = require("./checkout-flow.js");

const address = {
  line1: "4 Arum Avenue",
  line2: "",
  local_area: "Morningside Manor",
  city: "Sandton",
  region: "Gauteng",
  postal_code: "2196",
  country: "ZA",
};

test("a complete South African address can request rates", () => {
  assert.equal(flow.addressIsValid(address), true);
  assert.equal(flow.addressIsValid({ ...address, postal_code: "219" }), false);
  assert.equal(flow.addressIsValid({ ...address, country: "US" }), false);
  assert.equal(flow.quoteDecision({ valid: true, key: "a", quotedKey: "", ageMs: 0, inFlightKey: "" }), "request");
});

test("debounce collapses keystrokes and skips an unchanged quote", () => {
  const clock = { later(delay, fn) { this.delay = delay; this.fn = fn; return 1; }, clear() { this.cleared = true; } };
  const scheduler = flow.createQuoteScheduler(flow.debounceMs);
  let runs = 0;
  scheduler.push(() => { runs += 1; }, clock);
  scheduler.push(() => { runs += 1; }, clock);
  assert.equal(clock.cleared, true);
  assert.equal(clock.delay, 450);
  clock.fn();
  assert.equal(runs, 1);
  const key = flow.addressKey(address, [["product", 1]]);
  assert.equal(flow.quoteDecision({ valid: true, key: key, quotedKey: key, ageMs: 1000, inFlightKey: "" }), "wait");
  assert.equal(flow.quoteDecision({ valid: true, key: key, quotedKey: "", ageMs: 0, inFlightKey: key }), "wait");
  assert.equal(flow.quoteDecision({ valid: true, key: key, quotedKey: key, ageMs: flow.quoteLifetimeMs, inFlightKey: "" }), "request");
});

test("an address change and a missing or failed quote block payment", () => {
  const first = flow.addressKey(address, [["product", 1]]);
  const changed = flow.addressKey({ ...address, postal_code: "0002" }, [["product", 1]]);
  assert.notEqual(first, changed);
  const quote = { quotes: [{ service_code: "ECO", shipping_cents: 9500, total_cents: 159500, delivery_from: "2026-10-21T16:00:00+02:00", delivery_to: "2026-10-22T15:00:00+02:00" }] };
  const selected = { service_code: "ECO", shipping_cents: 9500 };
  assert.equal(flow.selectionIsCurrent(quote, selected, 1000), true);
  assert.equal(flow.selectionIsCurrent(quote, { service_code: "ECO", shipping_cents: 1 }, 1000), false);
  assert.equal(flow.selectionIsCurrent(null, selected, 1000), false);
  assert.equal(flow.canSubmit({ submitting: false, termsAccepted: true, quote: null, selected: selected, ageMs: 0 }), false);
  assert.equal(flow.displayTotal(150000, null).totalCents, null);
  assert.equal(flow.displayTotal(150000, quote.quotes[0]).totalCents, 159500);
  assert.match(flow.deliveryEstimate(quote.quotes[0]), /21 Oct 2026/);
  assert.equal(flow.deliveryEstimate({ service_code: "ECO" }), "");
});

test("Pay Now cannot be submitted twice and only the sandbox host is accepted", () => {
  const lock = flow.createSubmitLock();
  assert.equal(lock.tryLock(), true);
  assert.equal(lock.tryLock(), false);
  lock.release();
  assert.equal(lock.tryLock(), true);
  assert.equal(flow.payfastActionAllowed(flow.sandboxProcessUrl), true);
  assert.equal(flow.payfastActionAllowed("https://www.payfast.co.za/eng/process"), false);
  assert.equal(flow.payfastActionAllowed(""), false);
  const refused = flow.paymentAttempt({ ok: false, detail: "Payment is temporarily unavailable.", action: "", fields: null });
  assert.equal(refused.redirect, false);
  assert.equal(refused.message, "Payment is temporarily unavailable. The order is not paid.");
  const accepted = flow.paymentAttempt({
    ok: true,
    detail: "",
    action: flow.sandboxProcessUrl,
    fields: { merchant_id: "10000100", amount: "10.00" },
  });
  assert.equal(accepted.redirect, true);
  assert.equal(flow.paymentAttempt({ ok: true, action: "https://www.payfast.co.za/eng/process", fields: { amount: "10.00" } }).redirect, false);
  assert.equal(flow.customerName("Ada", "Lovelace"), "Ada Lovelace");
});

test("only Economy and Local Same Day Economy can be offered, with Economy selected by default", () => {
  const quotes = [
    { service_code: "LOF", shipping_cents: 8625, total_cents: 158625 },
    { service_code: "ECO", shipping_cents: 9500, total_cents: 159500 },
    { service_code: "LSE", shipping_cents: 10350, total_cents: 160350 },
    { service_code: "LSX", shipping_cents: 56000, total_cents: 206000 },
  ];
  const offered = flow.customerQuotes(quotes);
  assert.deepEqual(offered.map((option) => option.service_code), ["ECO", "LSE"]);
  assert.equal(flow.defaultServiceCode(quotes), "ECO");
  assert.equal(flow.selectionAfterQuote("", quotes), "ECO");
  assert.equal(flow.selectionAfterQuote("LSE", quotes), "LSE");
  assert.equal(flow.displayTotal(150000, offered[1]).totalCents, 160350);
  const withoutEconomy = [{ service_code: "LSE", shipping_cents: 10350, total_cents: 160350 }];
  assert.equal(flow.defaultServiceCode(withoutEconomy), "");
  assert.equal(flow.selectionAfterQuote("ECO", withoutEconomy), "");
  assert.equal(flow.paymentAvailable("sandbox"), true);
  assert.equal(flow.paymentAvailable("simulation"), false);
  assert.equal(flow.paymentAvailable("unavailable"), false);
});

test("customer pages do not show sandbox or simulation wording", () => {
  const root = path.join(__dirname, "..");
  const pages = ["checkout.html", "terms.html", "privacy.html", "shipping-and-returns.html", "index.html", "cart.html", "products.html"];
  const banned = [/sandbox/i, /simulated/i, /test checkout/i, /ShipLogic sandbox/i];
  pages.forEach((name) => {
    const text = fs.readFileSync(path.join(root, name), "utf8");
    banned.forEach((pattern) => assert.doesNotMatch(text, pattern, name));
  });
  const checkout = fs.readFileSync(path.join(__dirname, "checkout.js"), "utf8");
  assert.doesNotMatch(checkout, /ShipLogic sandbox|PayFast sandbox|Simulated test|simulated payment|Simulate successful/i);
  assert.match(checkout, /paymentFailureMessage/);
  assert.match(checkout, /releasePay\(\)/);
  assert.doesNotMatch(checkout, /form\.hidden = true;\s*form\.style\.display = "none";\s*rememberOrder/);
});

test("checkout markup stacks on small screens and places the summary before Pay Now", () => {
  const root = path.join(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "checkout.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "css", "styles.css"), "utf8");
  assert.equal(html.includes("data-quote-button"), false);
  assert.match(html, /Pay Now/);
  assert.ok(html.indexOf("data-order-summary") < html.indexOf("data-place-order"));
  assert.match(html, /name="given_name"/);
  assert.match(html, /name="family_name"/);
  assert.match(html, /checkout-grid--place/);
  assert.match(html, /checkout-grid--region/);
  const layout = css.slice(css.indexOf(".checkout-page"));
  assert.match(layout, /\.checkout-grid \{\s*display: grid;\s*gap: 0\.75rem;\s*\}/);
  assert.match(layout, /@media \(min-width: 48rem\) \{[\s\S]*\.checkout-grid--name/);
  assert.match(layout, /@media \(min-width: 64rem\) \{[\s\S]*\.checkout-summary/);
  assert.doesNotMatch(layout, /takealot/i);
});
