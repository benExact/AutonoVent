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

  function productSlug(product) {
    return product && typeof product.slug === "string" ? product.slug.trim().toLowerCase() : "";
  }

  function requestedSlug() {
    if (!/\/product\.html$/.test(window.location.pathname)) {
      return "";
    }
    return (new URLSearchParams(window.location.search).get("product") || "").trim().toLowerCase();
  }

  function isAutonovent(product) {
    return productSlug(product) === "autonovent";
  }

  function productPath(product) {
    const slug = productSlug(product);
    if (slug === "autonovent") {
      return "product.html";
    }
    return "product.html?product=" + encodeURIComponent(slug || (product && product.id) || "");
  }

  function setRobots(content) {
    let robots = document.querySelector('meta[name="robots"]');
    if (!content) {
      if (robots) {
        robots.remove();
      }
      return;
    }
    if (!robots) {
      robots = document.createElement("meta");
      robots.setAttribute("name", "robots");
      document.head.appendChild(robots);
    }
    robots.setAttribute("content", content);
  }

  function setProductMeta(title, text) {
    document.title = title;
    const description = document.querySelector('meta[name="description"]');
    if (description) {
      description.setAttribute("content", text);
    }
    const ogTitle = document.querySelector('meta[property="og:title"]');
    if (ogTitle) {
      ogTitle.setAttribute("content", title);
    }
    const ogDescription = document.querySelector('meta[property="og:description"]');
    if (ogDescription) {
      ogDescription.setAttribute("content", text);
    }
  }

  function showProductDetail(product, slug) {
    const story = !slug || slug === "autonovent";
    document.querySelectorAll("[data-autonovent-story]").forEach((node) => {
      node.hidden = !story;
    });
    if (!product || isAutonovent(product)) {
      if (!product && slug && slug !== "autonovent") {
        const heading = document.querySelector("[data-product-name]");
        const summary = document.querySelector("[data-product-summary]");
        if (heading) {
          heading.textContent = "Product not listed";
        }
        if (summary) {
          summary.textContent = "This product is not in the Omniprod shop.";
        }
        setProductMeta("Product not listed | Omniprod", "This product is not in the Omniprod shop.");
        setRobots("noindex, follow");
      }
      return;
    }
    setRobots("");
    const heading = document.querySelector("[data-product-name]");
    const summary = document.querySelector("[data-product-summary]");
    const image = document.querySelector("[data-product-image]");
    const hero = document.querySelector("[data-product-hero]");
    const text = typeof product.description === "string" && product.description.trim()
      ? product.description.trim()
      : product.name + " is listed in the Omniprod shop.";
    if (heading) {
      heading.textContent = product.name;
    }
    if (summary) {
      summary.textContent = text;
    }
    setProductMeta(product.name + " | Omniprod", text);
    if (image) {
      image.removeAttribute("srcset");
      image.alt = product.name;
      image.src = productImageSource(product);
    }
    if (hero) {
      hero.classList.remove("hero-media--installed");
      hero.classList.add("hero-media--product");
    }
  }

  function renderProducts(products, options) {
    options = options || {};
    const items = document.createDocumentFragment();
    let shown = 0;

    const slug = requestedSlug();
    const onDetail = /\/product\.html$/.test(window.location.pathname);
    const visibleProducts = onDetail
      ? products.filter((product) => productSlug(product) === (slug || "autonovent"))
      : products;
    if (onDetail) {
      showProductDetail(visibleProducts[0] || null, slug);
      if (!visibleProducts.length) {
        setStatus(slug && slug !== "autonovent" ? "This product is not in the shop." : "This product is not listed for purchase.");
        retry.hidden = false;
        return;
      }
    }

    visibleProducts.forEach((product) => {
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

      const figure = document.createElement("a");
      figure.className = "product-shot";
      figure.href = productPath(product);
      figure.setAttribute("aria-label", "View " + product.name);
      const image = document.createElement("img");
      const source = productImageSource(product);
      image.src = source;
      image.width = 800;
      image.height = 600;
      image.loading = "lazy";
      image.decoding = "async";
      image.alt = "";
      image.addEventListener("error", () => {
        if (image.dataset.fallback === "true") {
          return;
        }
        image.dataset.fallback = "true";
        image.src = "assets/images/product-placeholder.svg";
        image.alt = "";
      });
      figure.append(image);
      item.append(figure);

      const name = document.createElement("h3");
      const nameLink = document.createElement("a");
      nameLink.href = productPath(product);
      nameLink.textContent = product.name;
      name.append(nameLink);
      const priceLine = document.createElement("p");
      priceLine.className = "catalogue-price";
      priceLine.textContent = product.price_is_demo ? price + " · Test price — not a confirmed selling price" : price;
      item.append(name, priceLine);

      if (typeof product.description === "string" && product.description.trim()) {
        const description = document.createElement("p");
        description.className = "product-card__summary";
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
      const details = document.createElement("a");
      details.className = "button button--secondary";
      details.href = productPath(product);
      details.textContent = "View product";
      actions.append(details);
      const button = document.createElement("button");
      button.className = "button button--primary";
      button.type = "button";
      button.textContent = "Add to Cart";
      button.addEventListener("click", () => {
        if (!window.AutonoventCart) {
          return;
        }
        const before = window.AutonoventCart.read().find((line) => line.productId === product.id);
        window.AutonoventCart.add(product.id);
        const after = window.AutonoventCart.read().find((line) => line.productId === product.id);
        if (before && before.quantity >= 20 && after && after.quantity >= 20) {
          button.textContent = "Cart limit reached";
          button.disabled = true;
          return;
        }
        button.textContent = "Added";
      });
      actions.append(button);
      item.append(actions);
      items.append(item);
      shown += 1;
    });

    if (!shown) {
      if (options.emptyMessage) {
        setStatus(options.emptyMessage);
        retry.hidden = true;
        return;
      }
      setStatus("Products could not be loaded. Try again.");
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

  function publishProductSchema(products) {
    if (!/\/product\.html$/.test(window.location.pathname)) {
      return;
    }
    var origin = (window.location.origin || "").replace(/\/$/, "");
    if (!origin || origin === "null") {
      return;
    }
    var graph = [];
    products.forEach(function (product) {
      if (!product || typeof product.name !== "string" || !Number.isInteger(product.unit_price_cents) || product.price_is_demo) {
        return;
      }
      var price = (product.unit_price_cents / 100).toFixed(2);
      var node = {
        "@type": "Product",
        name: product.name,
        description: typeof product.description === "string" && product.description.trim()
          ? product.description.trim()
          : product.name + " is listed in the Omniprod shop.",
        brand: { "@type": "Brand", name: product.name },
        offers: {
          "@type": "Offer",
          priceCurrency: product.currency || "ZAR",
          price: price,
          availability: "https://schema.org/InStock",
          url: origin + "/" + productPath(product)
        }
      };
      if (typeof product.sku === "string" && product.sku.trim()) {
        node.sku = product.sku.trim();
      }
      if (typeof baseUrl === "string" && typeof product.image_url === "string" && product.image_url.indexOf("/media/products/") === 0) {
        node.image = baseUrl.replace(/\/$/, "") + product.image_url;
      }
      graph.push(node);
    });
    if (!graph.length) {
      return;
    }
    var script = document.getElementById("product-schema");
    if (!script) {
      script = document.createElement("script");
      script.id = "product-schema";
      script.type = "application/ld+json";
      document.head.appendChild(script);
    }
    script.textContent = JSON.stringify(graph.length === 1 ? Object.assign({ "@context": "https://schema.org" }, graph[0]) : {
      "@context": "https://schema.org",
      "@graph": graph
    });
  }

  const searchForm = document.querySelector("[data-catalogue-form]");
  const searchInput = document.querySelector("[data-catalogue-search]");
  const clearSearch = document.querySelector("[data-catalogue-clear]");
  const sortControl = document.querySelector("[data-catalogue-sort]");
  const resultCount = document.querySelector("[data-catalogue-count]");
  let loadedProducts = [];
  let searchTimer = 0;

  function listedProduct(product) {
    return Boolean(product && typeof product.name === "string" && Number.isInteger(product.unit_price_cents) && formatPrice(product.unit_price_cents, product.currency));
  }

  function shopProducts() {
    const query = searchInput ? searchInput.value : "";
    const mode = sortControl ? sortControl.value : "featured";
    const search = window.OmniprodCatalogueSearch;
    const listed = loadedProducts.filter(listedProduct);
    const matched = search ? listed.filter((product) => search.matchesProduct(product, query)) : listed;
    return search ? search.sortProducts(matched, mode) : matched;
  }

  function showResults() {
    const onDetail = /\/product\.html$/.test(window.location.pathname);
    if (clearSearch && searchInput) {
      clearSearch.hidden = !searchInput.value.trim();
    }
    if (onDetail) {
      renderProducts(loadedProducts);
      return;
    }
    const query = searchInput ? searchInput.value.trim() : "";
    const visible = shopProducts();
    if (resultCount) {
      resultCount.textContent = visible.length === 1 ? "1 product" : visible.length + " products";
    }
    renderProducts(visible, {
      emptyMessage: query
        ? "No products match “" + query + "”."
        : "Nothing is listed for sale at the moment."
    });
    if (searchInput && window.history && window.history.replaceState) {
      const url = new URL(window.location.href);
      if (query) {
        url.searchParams.set("q", query);
      } else {
        url.searchParams.delete("q");
      }
      window.history.replaceState(null, "", url);
    }
  }

  function loadCatalogue() {
    retry.hidden = true;
    setStatus("Loading products.");

    if (typeof baseUrl !== "string" || !baseUrl.trim()) {
      setStatus("The shop could not be reached.");
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

        loadedProducts = body.products;
        if (body.products.length === 0) {
          if (resultCount) {
            resultCount.textContent = "0 products";
          }
          setStatus("Nothing is listed for sale at the moment.");
          retry.hidden = true;
          return;
        }

        showResults();
        var detailSlug = requestedSlug();
        var schemaProducts = /\/product\.html$/.test(window.location.pathname)
          ? body.products.filter(function (product) { return productSlug(product) === (detailSlug || "autonovent"); })
          : body.products;
        publishProductSchema(schemaProducts);
      })
      .catch(() => {
        setStatus("Products could not be loaded. Try again.");
        retry.hidden = false;
      });
  }

  if (searchInput) {
    const initialQuery = new URLSearchParams(window.location.search).get("q");
    if (initialQuery) {
      searchInput.value = initialQuery;
    }
    searchInput.addEventListener("input", () => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(showResults, 200);
    });
  }
  if (searchForm) {
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      window.clearTimeout(searchTimer);
      showResults();
    });
  }
  if (clearSearch) {
    clearSearch.addEventListener("click", () => {
      if (searchInput) {
        searchInput.value = "";
        searchInput.focus();
      }
      window.clearTimeout(searchTimer);
      showResults();
    });
  }
  if (sortControl) {
    sortControl.addEventListener("change", showResults);
  }

  retry.addEventListener("click", loadCatalogue);
  loadCatalogue();
})();
