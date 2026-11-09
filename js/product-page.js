/* One product page for every slug. The address stays /product/{slug}. */

(function () {
  const page = document.querySelector("[data-product-page]");
  const status = document.querySelector("[data-product-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!page || !status || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");

  function requestedSlug() {
    const parts = window.location.pathname.split("/").filter(Boolean);
    const marker = parts.indexOf("product");
    if (marker >= 0 && parts[marker + 1] && parts[marker + 1] !== "product.html") {
      return decodeURIComponent(parts[marker + 1]).trim().toLowerCase();
    }
    return (new URLSearchParams(window.location.search).get("product") || "").trim().toLowerCase();
  }

  function setStatus(message) {
    status.hidden = !message;
    status.textContent = message || "";
  }

  function imageUrl(path) {
    if (typeof path === "string" && path.indexOf("/media/products/") === 0) {
      return endpoint + path;
    }
    return "/assets/images/product-placeholder.svg";
  }

  function money(cents, currency) {
    try {
      return new Intl.NumberFormat("en-ZA", { style: "currency", currency: currency || "ZAR" }).format(cents / 100);
    } catch (error) {
      return "";
    }
  }

  function setMeta(product, origin) {
    const summary = (product.short_description || product.description || product.name || "").trim();
    document.title = product.name + " | Omniprod";
    const description = document.querySelector('meta[name="description"]');
    if (description) {
      description.setAttribute("content", summary.slice(0, 300));
    }
    const canonical = origin + "/product/" + encodeURIComponent(product.slug);
    const link = document.querySelector('link[rel="canonical"]');
    if (link) {
      link.setAttribute("href", canonical);
    }
    const image = product.images && product.images[0] ? imageUrl(product.images[0].url) : imageUrl(product.image_url);
    [
      ["og:title", document.title],
      ["og:description", summary.slice(0, 300)],
      ["og:url", canonical],
      ["og:image", image],
    ].forEach((pair) => {
      const node = document.querySelector('meta[property="' + pair[0] + '"]');
      if (node) {
        node.setAttribute("content", pair[1]);
      }
    });
  }

  function render(product) {
    const price = money(product.unit_price_cents, product.currency);
    const images = Array.isArray(product.images) && product.images.length
      ? product.images
      : (product.image_url ? [{ url: product.image_url, thumb_url: product.image_url }] : []);
    page.hidden = false;
    page.replaceChildren();

    const layout = document.createElement("div");
    layout.className = "product-detail";
    const gallery = document.createElement("div");
    gallery.className = "product-detail__gallery";
    const main = document.createElement("img");
    main.className = "product-detail__main";
    main.width = 1200;
    main.height = 900;
    main.alt = product.name;
    main.src = images.length ? imageUrl(images[0].url) : "/assets/images/product-placeholder.svg";
    gallery.append(main);
    if (images.length > 1) {
      const thumbs = document.createElement("div");
      thumbs.className = "product-thumbs";
      images.forEach((image, index) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "product-thumbs__button";
        if (index === 0) {
          button.setAttribute("aria-current", "true");
        }
        const thumb = document.createElement("img");
        thumb.src = imageUrl(image.thumb_url || image.url);
        thumb.alt = "";
        thumb.width = 96;
        thumb.height = 72;
        thumb.loading = "lazy";
        button.append(thumb);
        button.addEventListener("click", () => {
          main.src = imageUrl(image.url);
          thumbs.querySelectorAll("button").forEach((item) => item.removeAttribute("aria-current"));
          button.setAttribute("aria-current", "true");
        });
        thumbs.append(button);
      });
      gallery.append(thumbs);
    }

    const info = document.createElement("div");
    info.className = "product-detail__info";
    const title = document.createElement("h1");
    title.textContent = product.name;
    const priceLine = document.createElement("p");
    priceLine.className = "catalogue-price";
    priceLine.textContent = product.price_is_demo ? price + " · Test price — not a confirmed selling price" : price;
    const stock = document.createElement("p");
    stock.className = product.in_stock === false ? "stock-note" : "stock-note stock-note--available";
    stock.textContent = product.in_stock === false ? "Out of stock" : "In stock";
    const summary = document.createElement("p");
    summary.textContent = product.short_description || product.description || "";
    info.append(title, priceLine, stock, summary);

    if (product.in_stock !== false) {
      const controls = document.createElement("div");
      controls.className = "button-row";
      const quantity = document.createElement("input");
      quantity.type = "number";
      quantity.min = "1";
      quantity.max = "20";
      quantity.value = "1";
      quantity.setAttribute("aria-label", "Quantity");
      const add = document.createElement("button");
      add.type = "button";
      add.className = "button button--primary";
      add.textContent = "Add to Cart";
      add.addEventListener("click", () => {
        if (!window.AutonoventCart) {
          return;
        }
        const chosen = Math.min(20, Math.max(1, Number(quantity.value) || 1));
        const existing = window.AutonoventCart.read().find((line) => line.productId === product.id);
        const next = Math.min(20, (existing ? existing.quantity : 0) + chosen);
        if (!existing) {
          window.AutonoventCart.add(product.id);
        }
        window.AutonoventCart.setQuantity(product.id, next);
        add.textContent = "Added";
      });
      controls.append(quantity, add);
      info.append(controls);
    }

    layout.append(gallery, info);
    page.append(layout);

    if (product.description && product.description !== product.short_description) {
      const copy = document.createElement("section");
      copy.className = "product-copy";
      const heading = document.createElement("h2");
      heading.textContent = "Description";
      const text = document.createElement("p");
      text.textContent = product.description;
      copy.append(heading, text);
      page.append(copy);
    }

    const specs = Array.isArray(product.specifications) ? product.specifications.filter((item) => item && item.label && item.value) : [];
    if (specs.length) {
      const section = document.createElement("section");
      section.className = "product-specs";
      const heading = document.createElement("h2");
      heading.textContent = "Specifications";
      const table = document.createElement("dl");
      specs.forEach((item) => {
        const term = document.createElement("dt");
        term.textContent = item.label;
        const detail = document.createElement("dd");
        detail.textContent = item.value;
        table.append(term, detail);
      });
      section.append(heading, table);
      page.append(section);
    }

    const sheet = product.specification_sheet;
    if (sheet && typeof sheet.filename === "string" && sheet.filename) {
      page.append(specificationSection(product.slug, sheet));
    }
  }

  function svgIcon(paths) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    paths.forEach((value) => {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", value);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.8");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.append(path);
    });
    return svg;
  }

  function sheetSize(bytes) {
    if (!Number.isFinite(bytes) || bytes < 1) {
      return "";
    }
    if (bytes < 1024 * 1024) {
      return Math.max(1, Math.round(bytes / 1024)) + " KB";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function specificationSection(slug, sheet) {
    const url = endpoint + "/api/v1/products/" + encodeURIComponent(slug) + "/specification";
    const section = document.createElement("section");
    section.className = "spec-sheet";
    section.setAttribute("aria-labelledby", "spec-sheet-heading");
    const copy = document.createElement("div");
    copy.className = "spec-sheet__copy";
    const eyebrow = document.createElement("p");
    eyebrow.className = "spec-sheet__eyebrow";
    eyebrow.textContent = "Product documentation";
    const heading = document.createElement("h2");
    heading.id = "spec-sheet-heading";
    heading.textContent = "Need more product details?";
    const text = document.createElement("p");
    text.textContent = "Download the official product specification sheet for technical information and specifications.";
    copy.append(eyebrow, heading, text);

    const action = document.createElement("div");
    action.className = "spec-sheet__action";
    const link = document.createElement("a");
    link.className = "spec-sheet__button";
    link.href = url;
    link.setAttribute("download", sheet.filename);
    const badge = document.createElement("span");
    badge.className = "spec-sheet__badge";
    badge.append(svgIcon(["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5"]));
    const badgeText = document.createElement("span");
    badgeText.textContent = "PDF";
    badge.append(badgeText);
    const label = document.createElement("span");
    label.className = "spec-sheet__label";
    label.textContent = "Download Specification Sheet";
    const arrow = document.createElement("span");
    arrow.className = "spec-sheet__arrow";
    arrow.append(svgIcon(["M12 4v11", "M7 10l5 5 5-5", "M5 20h14"]));
    link.append(badge, label, arrow);
    const meta = document.createElement("p");
    meta.className = "spec-sheet__meta";
    meta.textContent = ["PDF Document", sheetSize(sheet.size_bytes)].filter(Boolean).join(" · ");
    const status = document.createElement("p");
    status.className = "spec-sheet__status";
    status.setAttribute("role", "status");
    action.append(link, meta, status);
    section.append(copy, action);

    link.addEventListener("click", (event) => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) {
        return;
      }
      event.preventDefault();
      if (link.getAttribute("aria-busy") === "true") {
        return;
      }
      link.setAttribute("aria-busy", "true");
      status.textContent = "Preparing your download…";
      fetch(url, { headers: { Accept: "application/pdf" } })
        .then((response) => {
          if (response.status === 404) {
            throw new Error("missing");
          }
          if (!response.ok) {
            throw new Error("failed");
          }
          return response.blob();
        })
        .then((blob) => {
          const objectUrl = URL.createObjectURL(blob);
          const save = document.createElement("a");
          save.href = objectUrl;
          save.download = sheet.filename;
          document.body.append(save);
          save.click();
          save.remove();
          window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
          status.textContent = "Your download has started.";
        })
        .catch((error) => {
          if (error && error.message === "missing") {
            status.textContent = "The specification sheet is not available right now.";
            return;
          }
          status.textContent = "";
          window.location.assign(url);
        })
        .finally(() => {
          link.removeAttribute("aria-busy");
        });
    });
    return section;
  }

  const slug = requestedSlug();
  if (!slug) {
    setStatus("This product is not available.");
    return;
  }
  setStatus("Loading product.");
  fetch(endpoint + "/api/v1/products/" + encodeURIComponent(slug), { headers: { Accept: "application/json" } })
    .then((response) => {
      if (response.status === 404) {
        setStatus("This product is not available.");
        return null;
      }
      if (!response.ok) {
        setStatus("The shop could not be reached.");
        return null;
      }
      return response.json();
    })
    .then((product) => {
      if (!product) {
        return;
      }
      setStatus("");
      if (product.slug && product.slug !== slug && window.history && window.history.replaceState) {
        window.history.replaceState(null, "", "/product/" + encodeURIComponent(product.slug));
      }
      const origin = window.location.origin && window.location.origin !== "null" ? window.location.origin : "https://omniprod.co.za";
      setMeta(product, origin);
      render(product);
    })
    .catch(() => {
      setStatus("The shop could not be reached.");
    });
})();
