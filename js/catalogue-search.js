/* Search and sort for the loaded catalogue. It does not invent products. */

(function (root) {
  function queryTokens(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .split(/\s+/)
      .filter(Boolean);
  }

  function matchesProduct(product, query) {
    const tokens = queryTokens(query);
    if (!tokens.length || !product) {
      return true;
    }
    const haystack = [product.name, product.description, product.sku]
      .filter((value) => typeof value === "string")
      .join("\n")
      .toLowerCase();
    return tokens.every((token) => haystack.includes(token));
  }

  function sortProducts(products, mode) {
    const copy = products.slice();
    if (mode === "price-asc") {
      copy.sort((left, right) => left.unit_price_cents - right.unit_price_cents);
    } else if (mode === "price-desc") {
      copy.sort((left, right) => right.unit_price_cents - left.unit_price_cents);
    } else if (mode === "name") {
      copy.sort((left, right) => String(left.name).localeCompare(String(right.name), "en", { sensitivity: "base" }));
    }
    return copy;
  }

  root.OmniprodCatalogueSearch = {
    queryTokens: queryTokens,
    matchesProduct: matchesProduct,
    sortProducts: sortProducts
  };
})(typeof window !== "undefined" ? window : globalThis);
