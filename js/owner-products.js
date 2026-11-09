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
  const order = window.AutonoventGalleryOrder;
  let editingId = "";
  let galleryItems = [];
  let galleryProductId = "";
  let confirmingIndex = -1;
  let galleryBusy = false;
  const sheet = {
    productId: "",
    configured: false,
    available: false,
    name: "",
    size: null,
    pending: null,
    pendingUrl: "",
    remove: false,
    previewUrl: "",
  };
  let slugEdited = false;
  let saving = false;
  let deleting = false;
  const maxImageBytes = 5 * 1024 * 1024;
  const maxSheetBytes = 25 * 1024 * 1024;
  const publishWarning = "Upload a PDF before publishing with the specification sheet enabled.";
  const icons = {
    trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3",
    left: "M19 12H5M11 18l-6-6 6-6",
  };

  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", icons[name]);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2");
    path.setAttribute("stroke-linecap", "round");
    path.setAttribute("stroke-linejoin", "round");
    svg.append(path);
    return svg;
  }

  function fileSize(bytes) {
    if (!Number.isFinite(bytes)) {
      return "";
    }
    if (bytes < 1024 * 1024) {
      return Math.max(1, Math.round(bytes / 1024)) + " KB";
    }
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

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

  function galleryStatus(message) {
    setStatus(document.querySelector("[data-gallery-status]"), message);
  }

  function resetGallery(product) {
    galleryItems.forEach((item) => {
      if (item.kind === "pending") {
        URL.revokeObjectURL(item.url);
      }
    });
    const images = product && Array.isArray(product.images) ? product.images : [];
    galleryItems = images.map((image) => ({
      kind: "saved",
      id: image.id,
      url: imageSource({ image_url: image.thumb_url || image.url }),
    }));
    galleryProductId = product ? product.id : "";
    confirmingIndex = -1;
    const input = document.querySelector("#product-image");
    if (input) {
      input.value = "";
    }
    galleryStatus("");
    renderGallery();
  }

  function iconButton(name, label, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "icon-button " + className;
    button.setAttribute("aria-label", label);
    button.title = label;
    button.append(icon(name));
    return button;
  }

  function renderGallery() {
    const host = document.querySelector("[data-product-gallery]");
    const count = document.querySelector("[data-product-image-count]");
    const add = document.querySelector("[data-gallery-add]");
    if (count) {
      count.textContent = galleryItems.length + " of " + order.maxImages + " images";
    }
    if (add) {
      add.disabled = galleryBusy || order.room(galleryItems) === 0;
    }
    if (!host) {
      return;
    }
    host.replaceChildren();
    galleryItems.forEach((item, index) => {
      const card = document.createElement("li");
      card.className = "gallery-card";
      const frame = document.createElement("div");
      frame.className = "gallery-card__frame";
      const picture = document.createElement("img");
      picture.src = item.url;
      picture.alt = "Product image " + (index + 1);
      picture.width = 320;
      picture.height = 240;
      frame.append(picture);
      const position = document.createElement("span");
      position.className = "gallery-card__position";
      position.textContent = String(index + 1);
      position.title = index === 0 ? "Main image" : "Position " + (index + 1);
      frame.append(position);
      if (item.kind === "pending") {
        const fresh = document.createElement("span");
        fresh.className = "gallery-card__tag";
        fresh.textContent = "Not saved";
        frame.append(fresh);
      }
      const remove = iconButton("trash", "Delete image " + (index + 1), "gallery-card__delete");
      remove.disabled = galleryBusy;
      remove.addEventListener("click", () => {
        confirmingIndex = index;
        renderGallery();
        const confirm = host.querySelector("[data-gallery-confirm]");
        if (confirm) {
          confirm.focus();
        }
      });
      frame.append(remove);
      const earlier = iconButton("left", "Move image " + (index + 1) + " left", "gallery-card__move");
      earlier.disabled = galleryBusy || index === 0;
      earlier.addEventListener("click", () => moveImageLeft(index));
      frame.append(earlier);
      card.append(frame);
      if (confirmingIndex === index) {
        const prompt = document.createElement("div");
        prompt.className = "gallery-card__confirm";
        prompt.setAttribute("role", "group");
        prompt.setAttribute("aria-label", "Delete image " + (index + 1) + "?");
        const question = document.createElement("p");
        question.textContent = "Delete this image?";
        const yes = document.createElement("button");
        yes.type = "button";
        yes.className = "button button--primary button--compact";
        yes.textContent = "Delete";
        yes.setAttribute("data-gallery-confirm", "");
        yes.addEventListener("click", () => deleteImageAt(index));
        const no = document.createElement("button");
        no.type = "button";
        no.className = "button button--secondary button--compact";
        no.textContent = "Keep";
        no.addEventListener("click", () => {
          confirmingIndex = -1;
          renderGallery();
        });
        prompt.append(question, yes, no);
        card.append(prompt);
      }
      host.append(card);
    });
  }

  function addImages(files) {
    const problem = files.map(chosenImage).find(Boolean);
    if (problem) {
      galleryStatus(problem);
      return;
    }
    const room = order.room(galleryItems);
    if (!room) {
      galleryStatus("A product can have up to " + order.maxImages + " images. Delete one before adding another.");
      return;
    }
    files.slice(0, room).forEach((file) => {
      galleryItems.push({ kind: "pending", file: file, url: URL.createObjectURL(file) });
    });
    confirmingIndex = -1;
    renderGallery();
    galleryStatus(files.length > room ? "Only " + order.maxImages + " images can be kept. Extra images were not added." : "");
  }

  function putOrder(productId, ids) {
    return api("/api/v1/admin/products/" + encodeURIComponent(productId) + "/images/order", {
      method: "PUT",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrfFromCookie() },
      body: JSON.stringify({ image_ids: ids }),
    });
  }

  function moveImageLeft(index) {
    const previous = galleryItems;
    const before = order.savedIds(previous);
    galleryItems = order.moveLeft(previous, index);
    confirmingIndex = -1;
    renderGallery();
    const after = order.savedIds(galleryItems);
    if (!galleryProductId || before.join() === after.join()) {
      return;
    }
    galleryBusy = true;
    renderGallery();
    putOrder(galleryProductId, after).then(async (response) => {
      if (!response.ok) {
        galleryItems = previous;
        galleryStatus(await detailMessage(response));
        return;
      }
      galleryStatus("");
      loadProducts();
    }).catch(() => {
      galleryItems = previous;
      galleryStatus("The new image order could not be saved.");
    }).finally(() => {
      galleryBusy = false;
      renderGallery();
    });
  }

  function deleteImageAt(index) {
    const item = galleryItems[index];
    confirmingIndex = -1;
    if (!item) {
      renderGallery();
      return;
    }
    if (item.kind === "pending") {
      URL.revokeObjectURL(item.url);
      galleryItems = order.without(galleryItems, index);
      renderGallery();
      return;
    }
    galleryBusy = true;
    renderGallery();
    api("/api/v1/admin/products/" + encodeURIComponent(galleryProductId) + "/images/" + encodeURIComponent(item.id), {
      method: "DELETE",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
    }).then(async (response) => {
      if (!response.ok) {
        galleryStatus(await detailMessage(response));
        return;
      }
      galleryItems = galleryItems.filter((entry) => entry !== item);
      galleryStatus("Image deleted.");
      loadProducts();
    }).catch(() => {
      galleryStatus("The image could not be deleted.");
    }).finally(() => {
      galleryBusy = false;
      renderGallery();
    });
  }

  async function uploadGallery(saved) {
    const known = new Set((saved.images || []).map((image) => image.id));
    const uploaded = [];
    for (const item of galleryItems.filter((entry) => entry.kind === "pending")) {
      const data = new FormData();
      data.append("image", item.file);
      const response = await api("/api/v1/admin/products/" + encodeURIComponent(saved.id) + "/images", {
        method: "POST",
        headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
        body: data,
      });
      if (!response.ok) {
        throw new Error("An image was not saved. " + await detailMessage(response));
      }
      saved = await response.json();
      const added = (saved.images || []).find((image) => !known.has(image.id));
      if (added) {
        known.add(added.id);
        uploaded.push(added.id);
      }
    }
    if (!uploaded.length) {
      return saved;
    }
    const wanted = order.serverOrder(galleryItems, uploaded);
    const current = (saved.images || []).map((image) => image.id);
    if (wanted.length !== current.length || wanted.join() === current.join()) {
      return saved;
    }
    const reordered = await putOrder(saved.id, wanted);
    if (!reordered.ok) {
      throw new Error("The image order was not saved. " + await detailMessage(reordered));
    }
    return reordered.json();
  }

  function sheetMessage(message) {
    setStatus(document.querySelector("[data-spec-sheet-message]"), message);
  }

  function releaseSheetUrls() {
    if (sheet.pendingUrl) {
      URL.revokeObjectURL(sheet.pendingUrl);
    }
    if (sheet.previewUrl) {
      URL.revokeObjectURL(sheet.previewUrl);
    }
    sheet.pendingUrl = "";
    sheet.previewUrl = "";
  }

  function hidePreview() {
    const panel = document.querySelector("[data-spec-sheet-preview-panel]");
    const frame = document.querySelector("[data-spec-sheet-frame]");
    const toggle = document.querySelector("[data-spec-sheet-preview]");
    if (panel) {
      panel.hidden = true;
    }
    if (frame) {
      frame.removeAttribute("src");
    }
    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
      toggle.textContent = "Preview";
    }
  }

  function renderSheet(product) {
    hidePreview();
    releaseSheetUrls();
    const details = product && product.specification_sheet ? product.specification_sheet : {};
    sheet.productId = product ? product.id : "";
    sheet.configured = details.configured === true;
    sheet.available = details.file_available === true;
    sheet.name = details.original_name || "";
    sheet.size = Number.isFinite(details.size_bytes) ? details.size_bytes : null;
    sheet.pending = null;
    sheet.remove = false;
    const enabled = document.querySelector("[data-spec-sheet-enabled]");
    if (enabled) {
      enabled.checked = details.enabled === true;
    }
    const input = document.querySelector("[data-spec-sheet-input]");
    if (input) {
      input.value = "";
    }
    sheetMessage("");
    syncSheet();
  }

  function sheetWillHaveFile() {
    return Boolean(sheet.pending) || (sheet.configured && !sheet.remove);
  }

  function syncSheet() {
    const form = document.querySelector("[data-product-form]");
    const enabled = document.querySelector("[data-spec-sheet-enabled]");
    const on = Boolean(enabled && enabled.checked);
    const status = document.querySelector("[data-spec-sheet-status]");
    const controls = document.querySelector("[data-spec-sheet-controls]");
    const card = document.querySelector("[data-spec-sheet-file]");
    const empty = document.querySelector("[data-spec-sheet-empty]");
    const name = document.querySelector("[data-spec-sheet-name]");
    const meta = document.querySelector("[data-spec-sheet-meta]");
    const preview = document.querySelector("[data-spec-sheet-preview]");
    const replace = document.querySelector("[data-spec-sheet-replace]");
    const remove = document.querySelector("[data-spec-sheet-remove]");
    const undo = document.querySelector("[data-spec-sheet-undo]");
    if (status) {
      status.textContent = on ? "Enabled" : "Disabled";
      status.classList.toggle("status-pill--on", on);
    }
    if (controls) {
      controls.hidden = !on;
    }
    const showCard = Boolean(sheet.pending) || sheet.configured;
    if (card) {
      card.hidden = !showCard;
      card.classList.toggle("spec-file--removing", sheet.remove && !sheet.pending);
    }
    if (empty) {
      empty.hidden = showCard;
    }
    if (name) {
      name.textContent = sheet.pending ? sheet.pending.name : sheet.name;
    }
    if (meta) {
      if (sheet.pending) {
        meta.textContent = "PDF · " + fileSize(sheet.pending.size) + " · Uploads when you save";
      } else if (sheet.remove) {
        meta.textContent = "Will be removed when you save";
      } else if (sheet.configured && !sheet.available) {
        meta.textContent = "The file is missing on the server. Upload it again.";
      } else {
        meta.textContent = ["PDF", fileSize(sheet.size), "Uploaded"].filter(Boolean).join(" · ");
      }
    }
    const removing = sheet.remove && !sheet.pending;
    if (preview) {
      preview.hidden = removing || (!sheet.pending && !sheet.available);
    }
    if (replace) {
      replace.hidden = removing;
    }
    if (remove) {
      remove.hidden = removing;
    }
    if (undo) {
      undo.hidden = !removing;
    }
    const published = Boolean(form && form.active && form.active.checked);
    const note = document.querySelector("[data-spec-sheet-message]");
    if (on && published && !sheetWillHaveFile()) {
      sheetMessage(publishWarning);
    } else if (note && note.textContent === publishWarning) {
      sheetMessage("");
    }
  }

  function chosenSheet(file) {
    if (!file) {
      return "Choose a PDF file.";
    }
    if (!/\.pdf$/i.test(file.name) || (file.type && file.type !== "application/pdf")) {
      return "Upload the specification sheet as a PDF file.";
    }
    if (file.size > maxSheetBytes) {
      return "The PDF is too large. The limit is 25 MB.";
    }
    return "";
  }

  function selectSheet(file) {
    const problem = chosenSheet(file);
    if (problem) {
      sheetMessage(problem);
      return;
    }
    hidePreview();
    releaseSheetUrls();
    sheet.pending = file;
    sheet.pendingUrl = URL.createObjectURL(file);
    sheet.remove = false;
    sheetMessage("");
    syncSheet();
  }

  async function togglePreview() {
    const panel = document.querySelector("[data-spec-sheet-preview-panel]");
    const frame = document.querySelector("[data-spec-sheet-frame]");
    const toggle = document.querySelector("[data-spec-sheet-preview]");
    if (!panel || !frame || !toggle) {
      return;
    }
    if (!panel.hidden) {
      hidePreview();
      return;
    }
    let url = sheet.pendingUrl;
    if (!url && sheet.productId) {
      if (!sheet.previewUrl) {
        toggle.disabled = true;
        try {
          const response = await api("/api/v1/admin/products/" + encodeURIComponent(sheet.productId) + "/specification/file", {
            headers: { Accept: "application/pdf" },
          });
          if (!response.ok) {
            sheetMessage("The specification sheet could not be loaded for preview.");
            return;
          }
          sheet.previewUrl = URL.createObjectURL(await response.blob());
        } catch (error) {
          sheetMessage("The specification sheet could not be loaded for preview.");
          return;
        } finally {
          toggle.disabled = false;
        }
      }
      url = sheet.previewUrl;
    }
    if (!url) {
      return;
    }
    frame.src = url;
    panel.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    toggle.textContent = "Hide preview";
  }

  async function applySheet(saved, enableAfterUpload) {
    if (sheet.pending) {
      const data = new FormData();
      data.append("specification", sheet.pending);
      const uploaded = await api("/api/v1/admin/products/" + encodeURIComponent(saved.id) + "/specification", {
        method: "POST",
        headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
        body: data,
      });
      if (!uploaded.ok) {
        throw new Error(await detailMessage(uploaded));
      }
      saved = await uploaded.json();
    } else if (sheet.remove && sheet.configured) {
      const removed = await api("/api/v1/admin/products/" + encodeURIComponent(saved.id) + "/specification", {
        method: "DELETE",
        headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
      });
      if (!removed.ok) {
        throw new Error(await detailMessage(removed));
      }
      saved = await removed.json();
    }
    if (!enableAfterUpload) {
      return saved;
    }
    const enabled = await api("/api/v1/admin/products/" + encodeURIComponent(saved.id), {
      method: "PATCH",
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrfFromCookie() },
      body: JSON.stringify({ specification_enabled: true }),
    });
    if (!enabled.ok) {
      throw new Error(await detailMessage(enabled));
    }
    return enabled.json();
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
    resetGallery(product);
    renderSheet(product);
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
    const remove = form.querySelector("[data-product-delete]");
    if (remove) {
      remove.hidden = true;
      remove.disabled = false;
    }
    resetGallery(null);
    renderSheet(null);
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
    const addImage = form.querySelector("[data-gallery-add]");
    if (imageInput && addImage) {
      addImage.addEventListener("click", () => imageInput.click());
      imageInput.addEventListener("change", () => {
        const chosen = [...imageInput.files];
        imageInput.value = "";
        addImages(chosen);
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
    const sheetEnabled = form.querySelector("[data-spec-sheet-enabled]");
    const sheetInput = form.querySelector("[data-spec-sheet-input]");
    if (sheetEnabled) {
      sheetEnabled.addEventListener("change", syncSheet);
    }
    form.active.addEventListener("change", syncSheet);
    if (sheetInput) {
      sheetInput.addEventListener("change", () => {
        const file = sheetInput.files && sheetInput.files[0];
        sheetInput.value = "";
        if (file) {
          selectSheet(file);
        }
      });
      form.querySelectorAll("[data-spec-sheet-choose], [data-spec-sheet-replace]").forEach((button) => {
        button.addEventListener("click", () => sheetInput.click());
      });
    }
    const sheetRemove = form.querySelector("[data-spec-sheet-remove]");
    if (sheetRemove) {
      sheetRemove.addEventListener("click", () => {
        hidePreview();
        if (sheet.pending) {
          releaseSheetUrls();
          sheet.pending = null;
        } else {
          sheet.remove = true;
        }
        syncSheet();
      });
    }
    const sheetUndo = form.querySelector("[data-spec-sheet-undo]");
    if (sheetUndo) {
      sheetUndo.addEventListener("click", () => {
        sheet.remove = false;
        syncSheet();
      });
    }
    const sheetPreview = form.querySelector("[data-spec-sheet-preview]");
    if (sheetPreview) {
      sheetPreview.addEventListener("click", togglePreview);
    }
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
      const specifications = specRows();
      if (specifications.some((row) => !row.label || !row.value)) {
        setStatus(result, "Enter both a name and a value for each specification.");
        return;
      }
      const sheetOn = form.specification_enabled.checked;
      const hasSheetNow = sheet.configured && !sheet.remove;
      if (sheetOn && form.active.checked && !sheetWillHaveFile()) {
        setStatus(result, publishWarning);
        return;
      }
      const enableAfterUpload = sheetOn && form.active.checked && !hasSheetNow;
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
        specification_enabled: sheetOn && !enableAfterUpload,
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
        try {
          saved = await uploadGallery(saved);
        } catch (error) {
          fillForm(saved);
          setStatus(result, "The product was saved, but not every image was. " + error.message);
          loadProducts();
          return;
        }
        try {
          saved = await applySheet(saved, enableAfterUpload);
        } catch (error) {
          fillForm(saved);
          setStatus(result, "The product was saved, but the specification sheet was not. " + error.message);
          loadProducts();
          return;
        }
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
