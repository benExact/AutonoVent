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
    if ((currency || "ZAR") === "ZAR" && Number.isInteger(cents)) {
      const whole = String(Math.floor(Math.abs(cents) / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
      return (cents < 0 ? "-" : "") + "R" + whole + "." + String(Math.abs(cents) % 100).padStart(2, "0");
    }
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
      const name = document.createElement("h2");
      name.className = "cart-line__name";
      name.textContent = product ? product.name : "This product is not available for purchase.";
      row.append(productThumbnail(product), name, window.AutonoventCart.lineControls(line.productId, line.quantity, render));
      if (product && Number.isInteger(product.unit_price_cents)) {
        const lineCents = product.unit_price_cents * line.quantity;
        subtotal += lineCents;
        const prices = document.createElement("div");
        prices.className = "cart-line__prices";
        const unit = document.createElement("p");
        unit.className = "cart-line__unit";
        const unitLabel = document.createElement("span");
        unitLabel.className = "visually-hidden";
        unitLabel.textContent = "Unit price ";
        unit.append(unitLabel, document.createTextNode(money(product.unit_price_cents, product.currency)));
        if (product.price_is_demo) {
          const note = document.createElement("span");
          note.className = "cart-line__note";
          note.textContent = "Test price — not a confirmed selling price.";
          unit.append(note);
        }
        const lineTotal = document.createElement("p");
        lineTotal.className = "cart-line__total";
        const totalLabel = document.createElement("span");
        totalLabel.className = "visually-hidden";
        totalLabel.textContent = "Line total ";
        lineTotal.append(totalLabel, document.createTextNode(money(lineCents, product.currency)));
        prices.append(unit, lineTotal);
        row.append(prices);
      } else {
        blocked = true;
        const missing = document.createElement("p");
        missing.className = "cart-line__unavailable";
        missing.textContent = "This item cannot be purchased. Remove it to continue.";
        row.append(missing);
      }
      list.append(row);
    });
    host.append(list);
    const summary = document.createElement("div");
    summary.className = "cart-subtotal";
    if (blocked) {
      const note = document.createElement("p");
      note.textContent = "The subtotal is hidden until every item is available for purchase.";
      summary.append(note);
    } else {
      const label = document.createElement("p");
      label.className = "cart-subtotal__label";
      label.textContent = "Subtotal";
      const amount = document.createElement("p");
      amount.className = "cart-subtotal__amount";
      amount.textContent = money(subtotal, "ZAR");
      summary.append(label, amount);
    }
    host.append(summary);
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
