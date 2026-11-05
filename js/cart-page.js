/* Cart page. Displayed prices come from the catalogue response, not from storage. */

(function () {
  const status = document.querySelector("[data-cart-status]");
  const host = document.querySelector("[data-cart-lines]");
  const actions = document.querySelector("[data-cart-actions]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;
  const endpoint = typeof baseUrl === "string" ? baseUrl.replace(/\/$/, "") : "";

  if (!status || !host || !actions || !window.AutonoventCart) {
    return;
  }

  let catalogue = [];

  const imageFallback = "assets/images/product-placeholder.svg";

  function money(cents, currency) {
    try {
      return new Intl.NumberFormat("en-ZA", { style: "currency", currency: currency || "ZAR" }).format(cents / 100);
    } catch (error) {
      return "";
    }
  }

  function productImageSource(product) {
    if (product && typeof product.image_url === "string" && product.image_url.indexOf("/media/products/") === 0) {
      return endpoint + product.image_url;
    }
    return imageFallback;
  }

  function productThumbnail(product) {
    const image = document.createElement("img");
    image.className = "cart-thumb";
    image.width = 72;
    image.height = 72;
    image.decoding = "async";
    const source = productImageSource(product);
    image.alt = source === imageFallback || !product ? "" : product.name;
    image.src = source;
    image.addEventListener("error", function onError() {
      image.removeEventListener("error", onError);
      image.src = imageFallback;
      image.alt = "";
    });
    return image;
  }

  function render() {
    host.replaceChildren();
    const lines = window.AutonoventCart.read();
    if (!lines.length) {
      status.hidden = false;
      status.textContent = "Your cart is empty.";
      actions.hidden = true;
      return;
    }
    const list = document.createElement("ul");
    list.className = "cart-lines";
    let subtotal = 0;
    let blocked = false;
    lines.forEach((line) => {
      const product = catalogue.find((item) => item.id === line.productId);
      const row = document.createElement("li");
      row.className = "cart-line";
      const details = document.createElement("div");
      details.className = "cart-line__details";
      const name = document.createElement("h2");
      name.textContent = product ? product.name : "This product is not available for purchase.";
      details.append(name);
      if (product && Number.isInteger(product.unit_price_cents)) {
        const lineCents = product.unit_price_cents * line.quantity;
        subtotal += lineCents;
        const price = document.createElement("p");
        price.className = "catalogue-price";
        price.textContent = money(product.unit_price_cents, product.currency) + (product.price_is_demo ? " each. Test price — not a confirmed selling price." : " each.");
        details.append(price);
        if (typeof product.description === "string" && product.description.trim()) {
          const description = document.createElement("p");
          description.textContent = product.description;
          details.append(description);
        }
        const lineTotal = document.createElement("p");
        lineTotal.className = "cart-line__total";
        lineTotal.textContent = "Line total " + money(lineCents, product.currency);
        details.append(lineTotal);
      } else {
        blocked = true;
        const missing = document.createElement("p");
        missing.textContent = "This item cannot be purchased. Remove it to continue.";
        details.append(missing);
      }
      row.append(productThumbnail(product), details, window.AutonoventCart.lineControls(line.productId, line.quantity, render));
      list.append(row);
    });
    host.append(list);
    const total = document.createElement("p");
    total.className = "catalogue-price";
    total.textContent = blocked ? "The subtotal is hidden until every item is available for purchase." : "Subtotal " + money(subtotal, "ZAR") + ". Delivery is added at checkout.";
    host.append(total);
    status.hidden = true;
    actions.hidden = blocked;
  }

  if (!endpoint) {
    status.textContent = "The shop could not be reached.";
    return;
  }

  fetch(endpoint + "/api/v1/products", { headers: { Accept: "application/json" } })
    .then((response) => {
      if (!response.ok) {
        throw new Error("Catalogue request failed.");
      }
      return response.json();
    })
    .then((body) => {
      catalogue = body && Array.isArray(body.products) ? body.products : [];
      render();
    })
    .catch(() => {
      status.textContent = "Prices could not be loaded. Try again.";
    });
})();
