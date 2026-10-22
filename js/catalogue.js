/* Loads the public catalogue. It never invents a product or a price. */

(function () {
  const region = document.querySelector("[data-catalogue]");
  const status = document.querySelector("[data-catalogue-status]");
  const retry = document.querySelector("[data-catalogue-retry]");
  const list = document.querySelector("[data-catalogue-list]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;
  function productImageSource(product) {
    if (product && typeof product.image_url === "string" && product.image_url.indexOf("/media/products/") === 0) {
      return baseUrl.replace(/\/$/, "") + product.image_url;
    }
    return "assets/images/product-placeholder.svg";
  }

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

  function usesProductPhoto(product) {
    const name = typeof product.name === "string" ? product.name.toLowerCase() : "";
    const slug = typeof product.slug === "string" ? product.slug.toLowerCase() : "";
    return name.includes("autonovent") || slug.includes("autonovent");
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
      item.className = "product-card";
      item.id = "product-" + (product.slug || product.id);
      item.dataset.productId = product.id;

      const figure = document.createElement("figure");
      figure.className = "product-shot";
      const image = document.createElement("img");
      const source = productImageSource(product);
      image.src = source;
      image.width = 800;
      image.height = 600;
      image.loading = "lazy";
      image.decoding = "async";
      image.alt = source.indexOf("/media/products/") === -1 ? "" : product.name;
      figure.append(image);
      item.append(figure);

      const name = document.createElement("h3");
      name.textContent = product.name;
      const priceLine = document.createElement("p");
      priceLine.className = "catalogue-price";
      priceLine.textContent = product.price_is_demo ? price + " · Test price — not a confirmed selling price" : price;
      item.append(name, priceLine);

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

      const actions = document.createElement("div");
      actions.className = "button-row";
      if (usesProductPhoto(product)) {
        const details = document.createElement("a");
        details.className = "button button--secondary";
        details.href = "product.html";
        details.textContent = "Product details";
        actions.append(details);
      }
      const button = document.createElement("button");
      button.className = "button button--primary";
      button.type = "button";
      button.textContent = "Add to Cart";
      button.addEventListener("click", () => {
        if (!window.AutonoventCart) {
          return;
        }
        window.AutonoventCart.add(product.id);
        button.textContent = "Added";
      });
      actions.append(button);
      item.append(actions);
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
  }

  function loadCatalogue() {
    retry.hidden = true;
    setStatus("Loading products.");

    if (typeof baseUrl !== "string" || !baseUrl.trim()) {
      setStatus("The product list is not configured. No price is shown.");
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
          setStatus("No products are listed for purchase yet. A product appears here after it is active and has either a confirmed selling price or, in local development only, a labelled test price.");
          retry.hidden = true;
          return;
        }

        renderProducts(body.products);
      })
      .catch(() => {
        setStatus("The product list could not be loaded. No price is shown.");
        retry.hidden = false;
      });
  }

  retry.addEventListener("click", loadCatalogue);
  loadCatalogue();
})();
