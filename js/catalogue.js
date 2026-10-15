/* Loads the public catalogue. It never invents a product or a price. */

(function () {
  const region = document.querySelector("[data-catalogue]");
  const status = document.querySelector("[data-catalogue-status]");
  const retry = document.querySelector("[data-catalogue-retry]");
  const list = document.querySelector("[data-catalogue-list]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;

  if (!region || !status || !list || !retry) {
    return;
  }

  function setStatus(message) {
    status.hidden = false;
    status.textContent = message;
    list.replaceChildren();
  }

  function formatPrice(cents, currency) {
    try {
      return new Intl.NumberFormat("en-ZA", {
        style: "currency",
        currency: currency,
      }).format(cents / 100);
    } catch (error) {
      return "";
    }
  }

  function renderProducts(products) {
    const items = document.createDocumentFragment();
    let shown = 0;

    products.forEach((product) => {
      if (!product || typeof product.name !== "string" || !Number.isInteger(product.unit_price_cents)) {
        return;
      }

      const price = formatPrice(product.unit_price_cents, product.currency);

      if (!price) {
        return;
      }

      const item = document.createElement("li");
      const name = document.createElement("h3");
      const priceLine = document.createElement("p");

      name.textContent = product.name;
      priceLine.className = "catalogue-price";
      priceLine.textContent = price;
      item.append(name, priceLine);
      item.dataset.productId = product.id;

      if (typeof product.description === "string" && product.description.trim()) {
        const description = document.createElement("p");
        description.textContent = product.description;
        item.append(description);
      }

      if (typeof product.sku === "string" && product.sku.trim()) {
        const sku = document.createElement("p");
        sku.className = "placeholder-note";
        sku.textContent = "SKU " + product.sku;
        item.append(sku);
      }

      items.append(item);
      shown += 1;
    });

    if (!shown) {
      setStatus("The product list could not be read. No price is shown.");
      retry.hidden = false;
      return;
    }

    const catalogue = document.createElement("ul");
    catalogue.className = "catalogue-list";
    catalogue.append(items);
    status.hidden = true;
    retry.hidden = true;
    list.replaceChildren(catalogue);
    loadSimulation(catalogue);
  }

  function loadSimulation(catalogue) {
    if (typeof baseUrl !== "string" || !baseUrl.trim() || !window.AutonoventCart) {
      return;
    }
    fetch(baseUrl.replace(/\/$/, "") + "/api/v1/checkout/status", { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : null))
      .then((body) => {
        if (!body || body.simulation_enabled !== true) {
          return;
        }
        const note = document.createElement("p");
        note.className = "notice";
        note.textContent = "Simulated checkout is enabled. Delivery quotes and payments are test data, not Bob Go or PayFast.";
        catalogue.before(note);
        catalogue.querySelectorAll("li[data-product-id]").forEach((item) => {
          const button = document.createElement("button");
          button.className = "button button--primary";
          button.type = "button";
          button.textContent = "Add to simulated checkout";
          button.addEventListener("click", () => {
            window.AutonoventCart.add(item.dataset.productId);
            window.location.assign("checkout.html");
          });
          item.append(button);
        });
      })
      .catch(() => {});
  }

  function loadCatalogue() {
    retry.hidden = true;
    setStatus("Checking whether a product is listed for purchase.");

    if (typeof baseUrl !== "string" || !baseUrl.trim()) {
      setStatus("The product list is not configured. No price is shown. You can still request a quote.");
      return;
    }

    const endpoint = baseUrl.replace(/\/$/, "") + "/api/v1/products";

    fetch(endpoint, { headers: { Accept: "application/json" } })
      .then((response) => {
        if (!response.ok) {
          throw new Error("Catalogue request failed.");
        }

        return response.json();
      })
      .then((body) => {
        if (!body || !Array.isArray(body.products)) {
          throw new Error("Catalogue response was not a product list.");
        }

        if (body.products.length === 0) {
          setStatus("Autonovent is not listed for purchase yet. A selling price has not been published. Request a quote to ask about pricing and availability.");
          retry.hidden = true;
          return;
        }

        renderProducts(body.products);
      })
      .catch(() => {
        setStatus("The product list could not be loaded. No price is shown. You can still request a quote, or try again.");
        retry.hidden = false;
      });
  }

  retry.addEventListener("click", loadCatalogue);
  loadCatalogue();
})();
