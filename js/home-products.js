/* A short featured row. It uses the same catalogue as the shop and never invents a product. */

(function () {
  const status = document.querySelector("[data-home-products-status]");
  const host = document.querySelector("[data-home-products]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;
  if (!status || !host || typeof baseUrl !== "string") {
    return;
  }

  function money(cents, currency) {
    try {
      return new Intl.NumberFormat("en-ZA", { style: "currency", currency: currency }).format(cents / 100);
    } catch (error) {
      return "";
    }
  }

  function productPath(product) {
    const slug = product && typeof product.slug === "string" ? product.slug.trim().toLowerCase() : "";
    if (!slug) {
      return "products.html";
    }
    return "/product/" + encodeURIComponent(slug);
  }

  function imageSource(product) {
    if (product && typeof product.image_url === "string" && product.image_url.indexOf("/media/products/") === 0) {
      return baseUrl.replace(/\/$/, "") + product.image_url;
    }
    return "assets/images/product-placeholder.svg";
  }

  function render(products) {
    const items = document.createElement("ul");
    items.className = "catalogue-list";
    products.forEach((product) => {
      const price = money(product.unit_price_cents, product.currency);
      if (!price) {
        return;
      }
      const item = document.createElement("li");
      item.className = "product-card";
      const figure = document.createElement("a");
      figure.className = "product-shot";
      figure.href = productPath(product);
      figure.setAttribute("aria-label", "View " + product.name);
      const image = document.createElement("img");
      image.src = imageSource(product);
      image.width = 800;
      image.height = 600;
      image.alt = "";
      image.addEventListener("error", () => {
        image.src = "assets/images/product-placeholder.svg";
      });
      figure.append(image);
      const name = document.createElement("h3");
      const nameLink = document.createElement("a");
      nameLink.href = productPath(product);
      nameLink.textContent = product.name;
      name.append(nameLink);
      const priceLine = document.createElement("p");
      priceLine.className = "catalogue-price";
      priceLine.textContent = product.price_is_demo ? price + " · Test price — not a confirmed selling price" : price;
      item.append(figure, name, priceLine);
      if (typeof product.description === "string" && product.description.trim()) {
        const description = document.createElement("p");
        description.className = "product-card__summary";
        description.textContent = product.description.trim();
        item.append(description);
      }
      if (product.specification_sheet) {
        const sheet = document.createElement("p");
        sheet.className = "catalogue-spec-sheet";
        sheet.textContent = "Spec sheet available";
        item.append(sheet);
      }
      const actions = document.createElement("div");
      actions.className = "button-row";
      const details = document.createElement("a");
      details.className = "button button--secondary";
      details.href = productPath(product);
      details.textContent = "View product";
      const add = document.createElement("button");
      add.className = "button button--primary";
      add.type = "button";
      add.textContent = "Add to Cart";
      add.addEventListener("click", () => {
        if (!window.AutonoventCart) {
          return;
        }
        const before = window.AutonoventCart.read().find((line) => line.productId === product.id);
        window.AutonoventCart.add(product.id);
        const after = window.AutonoventCart.read().find((line) => line.productId === product.id);
        if (before && before.quantity >= 20 && after && after.quantity >= 20) {
          add.textContent = "Cart limit reached";
          add.disabled = true;
          return;
        }
        add.textContent = "Added";
      });
      actions.append(details, add);
      item.append(actions);
      items.append(item);
    });
    if (!items.childElementCount) {
      status.textContent = "Nothing is listed for sale at the moment.";
      host.replaceChildren();
      return;
    }
    status.hidden = true;
    host.replaceChildren(items);
  }

  fetch(baseUrl.replace(/\/$/, "") + "/api/v1/products", { headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : Promise.reject()))
    .then((body) => {
      const products = Array.isArray(body.products) ? body.products : [];
      render(products.filter((product) => product && typeof product.name === "string" && Number.isInteger(product.unit_price_cents)).slice(0, 4));
    })
    .catch(() => {
      status.textContent = "Products could not be loaded.";
    });
})();
