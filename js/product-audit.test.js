const assert = require("node:assert/strict");
const test = require("node:test");
const audit = require("./product-audit.js");

test("product audit labels, prices, and empty values stay readable", () => {
  assert.equal(audit.fieldLabel("unit_price_cents"), "Product Price");
  assert.equal(audit.fieldLabel("image_filename"), "Product Image");
  assert.equal(audit.fieldLabel("short_description"), "Short Description");
  assert.equal(audit.fieldLabel("specification_enabled"), "Specification Sheet Enabled");
  assert.equal(audit.fieldLabel("specification_stored_name"), "Specification Sheet File");
  assert.equal(audit.fieldLabel("active"), "Product Status");
  assert.equal(audit.fieldLabel("in_stock"), "Stock Availability");
  assert.equal(audit.formatValue("unit_price_cents", null), "—");
  assert.equal(audit.formatValue("unit_price_cents", 150000), "R1,500.00");
  assert.equal(audit.formatValue("active", true), "Active");
  assert.equal(audit.formatValue("active", false), "Inactive");
  assert.equal(audit.formatValue("specification_enabled", true), "Enabled");
  assert.equal(audit.formatValue("in_stock", false), "Out of stock");
  assert.equal(audit.formatValue("name", ""), "—");
  assert.equal(audit.formatValue("description", "Line one\nLine two"), "Line one\nLine two");
});

test("product audit dates and images do not expose a filesystem path", () => {
  const when = audit.formatWhen("2026-11-09T16:40:00.000Z");
  assert.match(when.date, /^\d{2} \w{3} 2026$/);
  assert.match(when.time, /^\d{2}:\d{2}$/);
  assert.equal(audit.imageUrl("http://127.0.0.1:8001", "../secret.jpg"), "");
  assert.equal(audit.imageUrl("http://127.0.0.1:8001", "C:\\var\\omniprod\\photo.jpg"), "");
  assert.equal(
    audit.imageUrl("http://127.0.0.1:8001/", "autonovent/4f2ad6636129bdd0.webp"),
    "http://127.0.0.1:8001/media/products/autonovent/4f2ad6636129bdd0.webp"
  );
  assert.equal(audit.formatValue("image_filename", "autonovent/4f2ad6636129bdd0.webp"), "4f2ad6636129bdd0.webp");
});

test("product audit shows the newest save first without changing the stored events", () => {
  const events = [
    { created_at: "2026-11-01T10:00:00.000Z", actor: "first@example.com" },
    { created_at: "2026-11-09T10:00:00.000Z", actor: "later@example.com" },
  ];
  const ordered = audit.newestFirst(events);
  assert.equal(ordered[0].actor, "later@example.com");
  assert.equal(events[0].actor, "first@example.com");
});
