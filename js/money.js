/* Rand amounts for the owner product form. The API stores integer cents. */

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.AutonoventMoney = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const maxCents = 2147483647;

  function centsFromRands(value) {
    const text = String(value || "").trim();
    if (!/^[0-9]+(?:[.,][0-9]{1,2})?$/.test(text)) {
      throw new Error("Enter the selling price in rands, using up to two decimal places.");
    }
    const parts = text.replace(",", ".").split(".");
    const whole = Number(parts[0]);
    const fraction = Number((parts[1] || "").padEnd(2, "0"));
    const cents = whole * 100 + fraction;
    if (!Number.isSafeInteger(cents) || cents < 1 || cents > maxCents) {
      throw new Error("Enter a selling price greater than R0.00.");
    }
    return cents;
  }

  function randsFromCents(cents) {
    if (!Number.isInteger(cents) || cents < 1) {
      return "";
    }
    return Math.floor(cents / 100) + "." + String(cents % 100).padStart(2, "0");
  }

  return {
    centsFromRands: centsFromRands,
    randsFromCents: randsFromCents,
  };
});
