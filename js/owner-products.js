/* Owner product records and the checkout checklist. The session cookie is not read here. */

(function () {
  const logout = document.querySelector("[data-auth-logout]");
  const authStatus = document.querySelector("[data-auth-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!logout || !authStatus || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  const moneyInput = window.AutonoventMoney;
  let editingId = "";
  let selectedFiles = [];
  let slugEdited = false;
  let saving = false;
  let deleting = false;
  const maxImageBytes = 5 * 1024 * 1024;

  function setStatus(node, message) {
    if (node) {
      node.textContent = message;
    }
  }

  function csrfFromCookie() {
    const parts = document.cookie.split("; ");
    const match = parts.find((part) => part.startsWith("autonovent_csrf="));
    return match ? decodeURIComponent(match.slice("autonovent_csrf=".length)) : "";
  }

  function api(path, options) {
    return fetch(endpoint + path, Object.assign({ credentials: "include", headers: { Accept: "application/json" } }, options));
  }

  function detailMessage(response) {
    return response.json().then(
      (body) => {
        if (typeof body.detail === "string") {
          return body.detail;
        }
        if (Array.isArray(body.detail) && body.detail[0] && typeof body.detail[0].msg === "string") {
          return body.detail[0].msg.replace(/^Value error,\s*/, "");
        }
        return "The product could not be saved.";
      },
      () => "The product service could not be reached."
    );
  }

  function money(cents) {
    if (!Number.isInteger(cents)) {
      return "Not set";
    }
    return new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR" }).format(cents / 100);
  }

  logout.addEventListener("click", () => {
    api("/api/v1/auth/logout", {
      method: "POST",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
    }).then((response) => {
      if (response.status === 204) {
        window.location.assign("login.html");
        return;
      }
      setStatus(authStatus, "Sign out could not be completed.");
    }).catch(() => {
      setStatus(authStatus, "Sign out could not be completed.");
    });
  });

  function requireOwner() {
    return api("/api/v1/auth/me").then((response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return null;
      }
      if (!response.ok) {
        setStatus(authStatus, "The sign-in service could not be reached.");
        return null;
      }
      return response.json();
    });
  }

  function imageSource(product) {
    if (product && typeof product.image_url === "string" && product.image_url.indexOf("/media/products/") === 0) {
      return endpoint + product.image_url;
    }
    return "../assets/images/product-placeholder.svg";
  }

  function slugify(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 80);
  }

  function clearPreview() {
    selectedFiles = [];
    const input = document.querySelector("#product-image");
    if (input) {
      input.value = "";
    }
  }

  function specRows() {
    return [...document.querySelectorAll("[data-spec-row]")].map((row) => ({
      label: row.querySelector("[data-spec-label]").value.trim(),
      value: row.querySelector("[data-spec-value]").value.trim(),
    })).filter((row) => row.label || row.value);
  }

  function addSpecRow(label, value) {
    const host = document.querySelector("[data-spec-rows]");
    if (!host) {
      return;
    }
    const row = document.createElement("div");
    row.className = "spec-row";
    row.setAttribute("data-spec-row", "");
    const name = document.createElement("input");
    name.type = "text";
    name.maxLength = 80;
    name.placeholder = "Name";
    name.setAttribute("data-spec-label", "");
    name.value = label || "";
    const detail = document.createElement("input");
    detail.type = "text";
    detail.maxLength = 200;
    detail.placeholder = "Value";
    detail.setAttribute("data-spec-value", "");
    detail.value = value || "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button--secondary";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => row.remove());
    row.append(name, detail, remove);
    host.append(row);
  }

  function renderProducts(products) {
    const host = document.querySelector("[data-products-list]");
    const status = document.querySelector("[data-products-status]");
    if (!host || !status) {
      return;
    }
    host.replaceChildren();
    if (!products.length) {
      setStatus(status, "No products have been saved.");
      return;
    }
    setStatus(status, "");
    products.forEach((product) => {
      const card = document.createElement("article");
      card.className = "owner-product-card";
      const figure = document.createElement("figure");
      figure.className = "owner-product-thumb";
      const image = document.createElement("img");
      image.src = imageSource(product);
      image.alt = product.name;
      image.width = 800;
      image.height = 600;
      image.loading = "lazy";
      image.decoding = "async";
      figure.append(image);
      const name = document.createElement("h3");
      name.textContent = product.name;
      const sku = document.createElement("p");
      sku.textContent = product.sku ? "SKU " + product.sku : "SKU not set";
      const price = document.createElement("p");
      price.className = "catalogue-price";
      price.textContent = money(product.unit_price_cents);
      const state = document.createElement("p");
      state.textContent = product.active ? "Active" : "Inactive";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "button button--secondary";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => fillForm(product));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button button--secondary";
      remove.setAttribute("data-product-delete", "");
      remove.textContent = "Delete product";
      remove.addEventListener("click", () => removeProduct(product.id, product.name));
      const actions = document.createElement("div");
      actions.className = "button-row";
      actions.append(edit, remove);
      card.append(figure, name, sku, price, state, actions);
      host.append(card);
    });
  }

  function showPanel() {
    const panel = document.querySelector("[data-product-panel]");
    if (panel) {
      panel.hidden = false;
    }
  }

  function fillForm(product) {
    const form = document.querySelector("[data-product-form]");
    const heading = document.querySelector("[data-product-form-heading]");
    if (!form || !heading || !moneyInput) {
      return;
    }
    clearPreview();
    form.reset();
    editingId = product.id;
    heading.textContent = "Edit product";
    slugEdited = true;
    form.name.value = product.name;
    form.slug.value = product.slug;
    form.short_description.value = product.short_description || "";
    form.description.value = product.description || "";
    form.sku.value = product.sku || "";
    form.price_rands.value = moneyInput.randsFromCents(product.unit_price_cents);
    form.in_stock.value = product.in_stock === false ? "false" : "true";
    form.active.checked = product.active === true;
    const specs = document.querySelector("[data-spec-rows]");
    if (specs) {
      specs.replaceChildren();
    }
    (product.specifications || []).forEach((item) => addSpecRow(item.label, item.value));
    renderGallery(product);
    const remove = document.querySelector("[data-product-form] [data-product-delete]");
    if (remove) {
      remove.hidden = false;
      remove.disabled = false;
    }
    setStatus(document.querySelector("[data-product-save]"), "");
    showPanel();
    loadAudit(product.id);
  }

  function loadAudit(productId) {
    const host = document.querySelector("[data-product-audit]");
    if (!host) {
      return;
    }
    host.replaceChildren();
    api("/api/v1/admin/products/" + encodeURIComponent(productId) + "/audit").then(async (response) => {
      if (!response.ok) {
        host.textContent = "Change history could not be loaded.";
        return;
      }
      const events = (await response.json()).events;
      if (!events.length) {
        host.textContent = "No changes have been recorded.";
        return;
      }
      const list = document.createElement("ol");
      list.className = "owner-history";
      events.forEach((event) => {
        const item = document.createElement("li");
        const when = new Date(event.created_at);
        const stamp = Number.isNaN(when.getTime()) ? "Not recorded" : new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(when);
        const parts = event.changes.map((change) => {
          const previous = change.previous === null || change.previous === undefined ? "empty" : String(change.previous);
          const next = change.new === null || change.new === undefined ? "empty" : String(change.new);
          return change.field + ": " + previous + " to " + next;
        });
        item.textContent = stamp + " — " + event.actor + " — " + parts.join("; ");
        list.append(item);
      });
      host.append(list);
    }).catch(() => {
      host.textContent = "Change history could not be loaded.";
    });
  }

  function clearForm() {
    const form = document.querySelector("[data-product-form]");
    const heading = document.querySelector("[data-product-form-heading]");
    const panel = document.querySelector("[data-product-panel]");
    if (!form || !heading || !panel) {
      return;
    }
    editingId = "";
    slugEdited = false;
    heading.textContent = "Add product";
    form.reset();
    const specs = document.querySelector("[data-spec-rows]");
    if (specs) {
      specs.replaceChildren();
    }
    const gallery = document.querySelector("[data-product-gallery]");
    if (gallery) {
      gallery.replaceChildren();
    }
    const remove = form.querySelector("[data-product-delete]");
    if (remove) {
      remove.hidden = true;
      remove.disabled = false;
    }
    clearPreview();
    setStatus(document.querySelector("[data-product-save]"), "");
    const history = document.querySelector("[data-product-audit]");
    if (history) {
      history.replaceChildren();
    }
    panel.hidden = true;
  }

  function openNewProduct() {
    clearForm();
    const panel = document.querySelector("[data-product-panel]");
    const heading = document.querySelector("[data-product-form-heading]");
    if (heading) {
      heading.textContent = "Add product";
    }
    if (panel) {
      panel.hidden = false;
      panel.scrollIntoView({ block: "start" });
    }
  }

  function loadProducts() {
    const status = document.querySelector("[data-products-status]");
    const retry = document.querySelector("[data-products-retry]");
    setStatus(status, "Loading products.");
    if (retry) {
      retry.hidden = true;
    }
    api("/api/v1/admin/products").then(async (response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (!response.ok) {
        setStatus(status, "Products could not be loaded.");
        if (retry) {
          retry.hidden = false;
        }
        return;
      }
      renderProducts((await response.json()).products);
    }).catch(() => {
      setStatus(status, "Products could not be loaded.");
      if (retry) {
        retry.hidden = false;
      }
    });
  }

  function chosenImage(file) {
    if (!file) {
      return "";
    }
    const allowed = file.type === "image/jpeg" || file.type === "image/png" || file.type === "image/webp";
    if (file.type && !allowed) {
      return "Use a JPEG, PNG, or WebP image.";
    }
    if (file.size > maxImageBytes) {
      return "The image is too large. Use a JPEG, PNG, or WebP under 5 MB.";
    }
    return "";
  }

  function removeProduct(productId, productName) {
    if (!productId || deleting || saving) {
      return;
    }
    const name = typeof productName === "string" && productName.trim() ? productName.trim() : "this product";
    const confirmed = window.confirm(
      "Delete " + name + "? It will be removed from the shop and this product list. Past orders keep their items and prices. You cannot restore it from this list."
    );
    if (!confirmed) {
      return;
    }
    deleting = true;
    document.querySelectorAll("[data-product-delete]").forEach((button) => {
      button.disabled = true;
    });
    const status = document.querySelector("[data-products-status]");
    setStatus(status, "Removing " + name + ".");
    api("/api/v1/admin/products/" + encodeURIComponent(productId), {
      method: "DELETE",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
    }).then(async (response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (response.status !== 204) {
        setStatus(status, await detailMessage(response));
        return;
      }
      if (editingId === productId) {
        clearForm();
      }
      setStatus(status, name + " was removed.");
      loadProducts();
    }).catch(() => {
      setStatus(status, "The product could not be removed.");
    }).finally(() => {
      deleting = false;
      document.querySelectorAll("[data-product-delete]").forEach((button) => {
        button.disabled = false;
      });
    });
  }

  function renderGallery(product) {
    const host = document.querySelector("[data-product-gallery]");
    const count = document.querySelector("[data-product-image-count]");
    if (!host) {
      return;
    }
    host.replaceChildren();
    const images = Array.isArray(product.images) ? product.images : [];
    if (count) {
      count.textContent = images.length + " of 4 images. The first image is the primary image.";
    }
    images.forEach((image, index) => {
      const card = document.createElement("figure");
      card.className = "owner-gallery__item";
      const picture = document.createElement("img");
      picture.src = imageSource({ image_url: image.thumb_url || image.url });
      picture.alt = "";
      picture.width = 160;
      picture.height = 120;
      const actions = document.createElement("div");
      actions.className = "button-row";
      if (index === 0) {
        const primary = document.createElement("span");
        primary.textContent = "Primary";
        actions.append(primary);
      }
      if (index > 0) {
        const earlier = document.createElement("button");
        earlier.type = "button";
        earlier.className = "button button--secondary";
        earlier.textContent = "Move earlier";
        earlier.addEventListener("click", () => moveImage(product, index, index - 1));
        actions.append(earlier);
      }
      const replace = document.createElement("input");
      replace.type = "file";
      replace.accept = "image/jpeg,image/png,image/webp";
      replace.setAttribute("aria-label", "Replace image");
      replace.addEventListener("change", () => {
        const file = replace.files && replace.files[0];
        const problem = chosenImage(file);
        if (problem) {
          setStatus(document.querySelector("[data-product-save]"), problem);
          return;
        }
        if (file) {
          replaceImage(product, image.id, file);
        }
      });
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button button--secondary";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => deleteImage(product, image.id));
      actions.append(replace, remove);
      card.append(picture, actions);
      host.append(card);
    });
  }

  function moveImage(product, from, to) {
    const ids = product.images.map((image) => image.id);
    const moved = ids.splice(from, 1)[0];
    ids.splice(to, 0, moved);
    api("/api/v1/admin/products/" + encodeURIComponent(product.id) + "/images/order", {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrfFromCookie() },
      body: JSON.stringify({ image_ids: ids }),
    }).then(async (response) => {
      if (!response.ok) {
        setStatus(document.querySelector("[data-product-save]"), await detailMessage(response));
        return;
      }
      fillForm(await response.json());
    });
  }

  function replaceImage(product, imageId, file) {
    const data = new FormData();
    data.append("image", file);
    api("/api/v1/admin/products/" + encodeURIComponent(product.id) + "/images/" + encodeURIComponent(imageId), {
      method: "POST",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
      body: data,
    }).then(async (response) => {
      if (!response.ok) {
        setStatus(document.querySelector("[data-product-save]"), await detailMessage(response));
        return;
      }
      fillForm(await response.json());
      loadProducts();
    });
  }

  function deleteImage(product, imageId) {
    api("/api/v1/admin/products/" + encodeURIComponent(product.id) + "/images/" + encodeURIComponent(imageId), {
      method: "DELETE",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
    }).then(async (response) => {
      if (!response.ok) {
        setStatus(document.querySelector("[data-product-save]"), await detailMessage(response));
        return;
      }
      fillForm(await response.json());
      loadProducts();
    });
  }

  function bindProductForm() {
    const form = document.querySelector("[data-product-form]");
    const clear = document.querySelector("[data-product-clear]");
    const add = document.querySelector("[data-product-add]");
    const result = document.querySelector("[data-product-save]");
    const submit = form && form.querySelector("[data-product-submit]");
    if (!form || !clear || !moneyInput) {
      return;
    }
    const imageInput = form.querySelector("#product-image");
    if (add) {
      add.addEventListener("click", openNewProduct);
    }
    clear.addEventListener("click", clearForm);
    const remove = form.querySelector("[data-product-delete]");
    if (remove) {
      remove.addEventListener("click", () => {
        if (!editingId) {
          return;
        }
        removeProduct(editingId, form.name.value);
      });
    }
    if (imageInput) {
      imageInput.addEventListener("change", () => {
        selectedFiles = [...imageInput.files];
        const problem = selectedFiles.map(chosenImage).find(Boolean);
        if (problem) {
          imageInput.value = "";
          selectedFiles = [];
          setStatus(result, problem);
          return;
        }
        setStatus(result, selectedFiles.length ? selectedFiles.length + " image" + (selectedFiles.length === 1 ? "" : "s") + " selected." : "");
      });
    }
    form.name.addEventListener("input", () => {
      if (!slugEdited && !editingId) {
        form.slug.value = slugify(form.name.value);
      }
    });
    form.slug.addEventListener("input", () => {
      slugEdited = true;
    });
    const addSpec = document.querySelector("[data-spec-add]");
    if (addSpec) {
      addSpec.addEventListener("click", () => addSpecRow("", ""));
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (saving) {
        return;
      }
      let price;
      try {
        price = moneyInput.centsFromRands(form.price_rands.value);
      } catch (error) {
        setStatus(result, error.message);
        return;
      }
      const imageProblem = selectedFiles.map(chosenImage).find(Boolean);
      if (imageProblem) {
        setStatus(result, imageProblem);
        return;
      }
      const specifications = specRows();
      if (specifications.some((row) => !row.label || !row.value)) {
        setStatus(result, "Enter both a name and a value for each specification.");
        return;
      }
      const body = {
        name: form.name.value,
        slug: form.slug.value,
        short_description: form.short_description.value,
        description: form.description.value,
        sku: form.sku.value,
        price_rands: form.price_rands.value.trim(),
        currency: "ZAR",
        active: form.active.checked,
        in_stock: form.in_stock.value !== "false",
        specifications: specifications,
      };
      if (!price) {
        setStatus(result, "Enter a selling price greater than R0.00.");
        return;
      }
      const path = editingId ? "/api/v1/admin/products/" + encodeURIComponent(editingId) : "/api/v1/admin/products";
      saving = true;
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Saving…";
      }
      setStatus(result, "Saving.");
      api(path, {
        method: editingId ? "PATCH" : "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfFromCookie(),
        },
        body: JSON.stringify(body),
      }).then(async (response) => {
        if (response.status === 401) {
          window.location.assign("login.html");
          return;
        }
        if (!response.ok) {
          setStatus(result, await detailMessage(response));
          return;
        }
        let saved = await response.json();
        for (const pending of selectedFiles) {
          const data = new FormData();
          data.append("image", pending);
          const uploaded = await api("/api/v1/admin/products/" + encodeURIComponent(saved.id) + "/images", {
            method: "POST",
            headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
            body: data,
          });
          if (!uploaded.ok) {
            setStatus(result, "The product was saved, but an image was not. " + await detailMessage(uploaded));
            fillForm(saved);
            loadProducts();
            return;
          }
          saved = await uploaded.json();
        }
        clearPreview();
        fillForm(saved);
        setStatus(result, "Saved.");
        loadProducts();
      }).catch(() => {
        setStatus(result, "The product service could not be reached.");
      }).finally(() => {
        saving = false;
        if (submit) {
          submit.disabled = false;
          submit.textContent = "Save product";
        }
      });
    });
  }

  requireOwner().then((owner) => {
    if (!owner) {
      return;
    }
    logout.hidden = false;
    setStatus(authStatus, owner.email);
    if (document.querySelector("[data-products-list]")) {
      const retry = document.querySelector("[data-products-retry]");
      if (retry) {
        retry.addEventListener("click", loadProducts);
      }
      bindProductForm();
      loadProducts();
    }
  }).catch(() => {
    setStatus(authStatus, "The sign-in service could not be reached.");
  });
})();
