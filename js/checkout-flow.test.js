const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
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
  assert.equal(flow.paymentWatchDecision(1, "pending"), "wait");
  assert.equal(flow.paymentWatchDecision(2, "paid"), "show");
  assert.equal(flow.paymentWatchDecision(flow.paymentWatchLimit, "pending"), "show");
  assert.equal(flow.paymentWatchIntervalMs, 2000);
  assert.match(checkout, /paymentFailureMessage/);
  assert.match(checkout, /paymentWatchDecision/);
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

test("product prices use rands and shop thumbnails keep their shape", () => {
  const money = require("./money.js");
  assert.equal(money.centsFromRands("1.00"), 100);
  assert.equal(money.centsFromRands("1550.00"), 155000);
  assert.equal(money.centsFromRands("1550.50"), 155050);
  assert.equal(money.randsFromCents(155050), "1550.50");
  assert.throws(() => money.centsFromRands("0"), /greater than R0\.00/);
  assert.throws(() => money.centsFromRands("-1"), /two decimal places/);
  assert.throws(() => money.centsFromRands("abc"), /two decimal places/);
  assert.throws(() => money.centsFromRands("1550.555"), /two decimal places/);
  const catalogue = fs.readFileSync(path.join(__dirname, "catalogue.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "..", "css", "styles.css"), "utf8");
  const owner = fs.readFileSync(path.join(__dirname, "..", "owner", "products.html"), "utf8");
  assert.match(catalogue, /image_url/);
  assert.doesNotMatch(catalogue, /autonovent-roof-sunset-card/);
  assert.match(css, /\.product-card \.product-shot img \{[\s\S]*object-fit: contain;/);
  assert.match(catalogue, /product-placeholder\.svg/);
  const ownerScript = fs.readFileSync(path.join(__dirname, "owner-products.js"), "utf8");
  assert.match(ownerScript, /Delete product/);
  assert.match(ownerScript, /method: "DELETE"/);
  assert.match(ownerScript, /window\.confirm\(\s*"Delete " \+ name/);
  assert.match(css, /@media \(min-width: 48rem\) \{[\s\S]*\.owner-product-grid/);
  assert.match(owner, /Add Product/);
  assert.match(owner, /name="price_rands"/);
  assert.match(owner, />R</);
});

test("checkout keeps a signed-in verification cookie instead of sending an empty token", () => {
  const checkout = fs.readFileSync(path.join(__dirname, "checkout.js"), "utf8");
  assert.match(checkout, /function csrfFromCookie\(\)/);
  assert.match(checkout, /autonovent_csrf=/);
  assert.match(checkout, /body\.csrf_token \|\| csrfFromCookie\(\)/);
  assert.match(checkout, /if \(existing\) \{\s*return Promise\.resolve\(existing\);/);
});

test("owner navigation no longer includes readiness and orders can download a PDF", () => {
  const root = path.join(__dirname, "..");
  const orders = fs.readFileSync(path.join(root, "owner", "orders.html"), "utf8");
  const order = fs.readFileSync(path.join(root, "owner", "order.html"), "utf8");
  const products = fs.readFileSync(path.join(root, "owner", "products.html"), "utf8");
  const portal = fs.readFileSync(path.join(__dirname, "owner-portal.js"), "utf8");
  assert.equal(fs.existsSync(path.join(root, "owner", "readiness.html")), false);
  assert.doesNotMatch(orders + order + products, /readiness\.html/);
  assert.match(portal, /Download PDF/);
  assert.match(portal, /\/document/);
});

test("public pages have unique titles and private routes stay out of the sitemap", () => {
  const root = path.join(__dirname, "..");
  const pages = [
    "index.html",
    "product.html",
    "how-it-works.html",
    "installation.html",
    "products.html",
    "terms.html",
    "privacy.html",
    "shipping-and-returns.html",
    "about.html",
    "contact.html"
  ];
  const titles = pages.map((name) => {
    const html = fs.readFileSync(path.join(root, name), "utf8");
    assert.match(html, /lang="en-ZA"/);
    assert.match(html, /js\/seo\.js/);
    assert.doesNotMatch(html, /name="robots" content="noindex/);
    const title = html.match(/<title>([^<]+)<\/title>/);
    const description = html.match(/<meta name="description" content="([^"]+)"/);
    assert.ok(title && title[1].length > 10);
    assert.ok(description && description[1].length > 40);
    return title[1];
  });
  assert.equal(new Set(titles).size, titles.length);
  const cart = fs.readFileSync(path.join(root, "cart.html"), "utf8");
  const checkout = fs.readFileSync(path.join(root, "checkout.html"), "utf8");
  const owner = fs.readFileSync(path.join(root, "owner", "orders.html"), "utf8");
  assert.match(cart, /noindex, follow/);
  assert.match(checkout, /noindex, follow/);
  assert.match(owner, /noindex, nofollow/);
  const sitemap = fs.readFileSync(path.join(root, "sitemap.xml"), "utf8");
  assert.match(sitemap, /product\.html/);
  assert.match(sitemap, /products\.html/);
  assert.match(sitemap, /about\.html/);
  assert.match(sitemap, /contact\.html/);
  assert.doesNotMatch(sitemap, /cart\.html|checkout\.html|owner\//);
  const catalogue = fs.readFileSync(path.join(__dirname, "catalogue.js"), "utf8");
  assert.match(catalogue, /"@type": "Product"/);
  assert.match(catalogue, /"@type": "Offer"/);
  assert.doesNotMatch(catalogue, /aggregateRating|review/);
});

test("catalogue search matches part of a name, description or SKU and can be sorted", () => {
  const context = { window: {} };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, "catalogue-search.js"), "utf8"), context);
  const search = context.window.OmniprodCatalogueSearch;
  const products = [
    { name: "Autonovent", description: "A vent for a canopy to reduce dust intake.", sku: "AV001", unit_price_cents: 150000 },
    { name: "Parcel Tape", description: "Wide tape for closing a carton.", sku: "PT9", unit_price_cents: 4500 }
  ];
  assert.equal(search.matchesProduct(products[0], "  DUST "), true);
  assert.equal(search.matchesProduct(products[0], "av001"), true);
  assert.equal(search.matchesProduct(products[1], "canopy vent"), false);
  assert.equal(search.matchesProduct(products[0], "canopy vent"), true);
  assert.deepEqual(search.sortProducts(products, "price-asc").map((product) => product.name), ["Parcel Tape", "Autonovent"]);
  assert.deepEqual(search.sortProducts(products, "price-desc").map((product) => product.name), ["Autonovent", "Parcel Tape"]);
  assert.deepEqual(search.sortProducts(products, "name").map((product) => product.name), ["Autonovent", "Parcel Tape"]);
  assert.deepEqual(search.sortProducts(products, "featured").map((product) => product.name), ["Autonovent", "Parcel Tape"]);
  const home = fs.readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const shop = fs.readFileSync(path.join(__dirname, "..", "products.html"), "utf8");
  const catalogue = fs.readFileSync(path.join(__dirname, "catalogue.js"), "utf8");
  assert.match(home, /Shop All Products/);
  assert.match(home, /data-store-hero/);
  assert.match(home, /href="products\.html"/);
  assert.doesNotMatch(home, /data-catalogue-list/);
  assert.match(shop, /data-catalogue-search/);
  assert.match(shop, /data-catalogue-list/);
  assert.match(catalogue, /\/product\//);
  assert.doesNotMatch(home, /name="robots" content="noindex/);
});

test("pretty product urls use one template and leave the API alone", () => {
  const root = path.join(__dirname, "..");
  const page = fs.readFileSync(path.join(root, "product.html"), "utf8");
  const script = fs.readFileSync(path.join(__dirname, "product-page.js"), "utf8");
  const nginx = fs.readFileSync(path.join(root, "deploy", "nginx", "product-slug.conf"), "utf8");
  assert.match(page, /data-product-page/);
  assert.match(script, /\/api\/v1\/products\//);
  assert.match(script, /This product is not available/);
  assert.match(nginx, /location \^~ \/api\//);
  assert.match(nginx, /try_files \/product\.html =404/);
  assert.match(nginx, /\/product\/\[a-z0-9\]/);
});

test("cart items show the catalogue image beside the existing controls", () => {
  const page = fs.readFileSync(path.join(__dirname, "cart-page.js"), "utf8");
  const css = fs.readFileSync(path.join(__dirname, "..", "css", "styles.css"), "utf8");
  assert.match(page, /image_url/);
  assert.match(page, /\/media\/products\//);
  assert.match(page, /product-placeholder\.svg/);
  assert.match(page, /cart-thumb/);
  assert.match(page, /Line total /);
  assert.match(css, /\.cart-thumb \{[\s\S]*width: 3\.75rem;[\s\S]*height: 3\.75rem;[\s\S]*object-fit: cover;/);
  assert.match(css, /@media \(min-width: 48rem\) \{[\s\S]*\.cart-thumb \{[\s\S]*width: 4\.5rem;[\s\S]*height: 4\.5rem;/);
});
