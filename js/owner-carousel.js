/* Owner homepage carousel. The session cookie is sent with each request. */

(function () {
  const logout = document.querySelector("[data-auth-logout]");
  const authStatus = document.querySelector("[data-auth-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!logout || !authStatus || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  const maxImageBytes = 5 * 1024 * 1024;
  const allowedTypes = ["image/jpeg", "image/png", "image/webp"];
  let editingId = "";
  let selectedFile = null;
  let previewUrl = "";
  let saving = false;

  function setStatus(node, message) {
    if (node) {
      node.textContent = message;
    }
  }

  function csrfFromCookie() {
    const match = document.cookie.split("; ").find((part) => part.startsWith("autonovent_csrf="));
    return match ? decodeURIComponent(match.slice("autonovent_csrf=".length)) : "";
  }

  function api(path, options) {
    return fetch(endpoint + path, Object.assign({ credentials: "include", headers: { Accept: "application/json" } }, options));
  }

  function detailMessage(response, fallback) {
    return response.json().then(
      (body) => (typeof body.detail === "string" ? body.detail : fallback),
      () => fallback
    );
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
    }).catch(() => setStatus(authStatus, "Sign out could not be completed."));
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
      logout.hidden = false;
      return response.json();
    });
  }

  function imageSource(slide) {
    if (slide && typeof slide.image_url === "string" && slide.image_url.indexOf("/media/carousel/") === 0) {
      return endpoint + slide.image_url;
    }
    return "";
  }

  function clearPreview() {
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
      previewUrl = "";
    }
    selectedFile = null;
    const preview = document.querySelector("[data-slide-preview]");
    const input = document.querySelector("#slide-image");
    if (preview) {
      preview.hidden = true;
      preview.removeAttribute("src");
    }
    if (input) {
      input.value = "";
    }
  }

  function showPreview(src, alt) {
    const preview = document.querySelector("[data-slide-preview]");
    if (!preview) {
      return;
    }
    preview.src = src;
    preview.alt = alt || "Banner preview";
    preview.hidden = false;
  }

  function closeForm() {
    const panel = document.querySelector("[data-slide-panel]");
    const form = document.querySelector("[data-slide-form]");
    if (panel) {
      panel.hidden = true;
    }
    if (form) {
      form.reset();
    }
    editingId = "";
    clearPreview();
  }

  function openForm(slide) {
    const panel = document.querySelector("[data-slide-panel]");
    const heading = document.querySelector("[data-slide-form-heading]");
    const form = document.querySelector("[data-slide-form]");
    if (!panel || !form) {
      return;
    }
    editingId = slide ? slide.id : "";
    heading.textContent = slide ? "Edit slide" : "Add slide";
    form.elements.title.value = slide && slide.title ? slide.title : "";
    form.elements.message.value = slide && slide.message ? slide.message : "";
    form.elements.display_order.value = slide ? String(slide.display_order) : "0";
    form.elements.enabled.checked = slide ? Boolean(slide.enabled) : true;
    clearPreview();
    if (slide && imageSource(slide)) {
      showPreview(imageSource(slide), slide.title || "Current banner");
    }
    panel.hidden = false;
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function render(slides) {
    const host = document.querySelector("[data-carousel-list]");
    const status = document.querySelector("[data-carousel-status]");
    if (!host || !status) {
      return;
    }
    host.replaceChildren();
    if (!slides.length) {
      status.textContent = "No slides yet. Add one to show a banner on the homepage.";
      return;
    }
    status.textContent = "";
    slides.forEach((slide) => {
      const card = document.createElement("article");
      card.className = "owner-slide-card";
      const image = document.createElement("img");
      image.src = imageSource(slide);
      image.alt = slide.title || "Uploaded banner";
      card.appendChild(image);
      const summary = document.createElement("p");
      summary.textContent = (slide.title || "Untitled slide") + " · order " + slide.display_order + " · " + (slide.enabled ? "enabled" : "disabled");
      card.appendChild(summary);
      const row = document.createElement("div");
      row.className = "button-row";
      const edit = document.createElement("button");
      edit.className = "button button--secondary";
      edit.type = "button";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => openForm(slide));
      const remove = document.createElement("button");
      remove.className = "button button--secondary";
      remove.type = "button";
      remove.textContent = "Delete";
      remove.addEventListener("click", () => removeSlide(slide));
      row.append(edit, remove);
      card.appendChild(row);
      host.appendChild(card);
    });
  }

  function load() {
    return api("/api/v1/admin/carousel").then((response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (!response.ok) {
        setStatus(document.querySelector("[data-carousel-status]"), "The slides could not be loaded.");
        return;
      }
      return response.json().then((body) => render(Array.isArray(body.slides) ? body.slides : []));
    }).catch(() => setStatus(document.querySelector("[data-carousel-status]"), "The slides could not be loaded."));
  }

  function removeSlide(slide) {
    const name = slide.title || "this slide";
    if (!window.confirm("Delete " + name + "?")) {
      return;
    }
    api("/api/v1/admin/carousel/" + slide.id, {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfFromCookie() },
    }).then((response) => {
      if (response.status === 204) {
        setStatus(document.querySelector("[data-carousel-status]"), "The slide was deleted.");
        closeForm();
        return load();
      }
      return detailMessage(response, "The slide could not be deleted.").then((message) => {
        setStatus(document.querySelector("[data-carousel-status]"), message);
      });
    }).catch(() => setStatus(document.querySelector("[data-carousel-status]"), "The slide could not be deleted."));
  }

  document.querySelector("#slide-image").addEventListener("change", (event) => {
    const file = event.target.files && event.target.files[0];
    const status = document.querySelector("[data-carousel-status]");
    selectedFile = null;
    if (!file) {
      return;
    }
    if (!allowedTypes.includes(file.type) || file.size > maxImageBytes || file.size === 0) {
      event.target.value = "";
      setStatus(status, "Choose a JPEG, PNG, or WebP image up to 5 MB.");
      return;
    }
    if (previewUrl) {
      URL.revokeObjectURL(previewUrl);
    }
    selectedFile = file;
    previewUrl = URL.createObjectURL(file);
    showPreview(previewUrl, "Banner preview");
  });

  document.querySelector("[data-slide-add]").addEventListener("click", () => openForm(null));
  document.querySelector("[data-slide-cancel]").addEventListener("click", closeForm);

  document.querySelector("[data-slide-form]").addEventListener("submit", (event) => {
    event.preventDefault();
    if (saving) {
      return;
    }
    const form = event.currentTarget;
    const status = document.querySelector("[data-carousel-status]");
    if (!editingId && !selectedFile) {
      setStatus(status, "Choose a banner image before saving.");
      return;
    }
    const order = Number(form.elements.display_order.value);
    if (!Number.isInteger(order) || order < 0 || order > 9999) {
      setStatus(status, "Choose a display order from 0 to 9999.");
      return;
    }
    saving = true;
    const fields = {
      title: form.elements.title.value,
      message: form.elements.message.value,
      display_order: order,
      enabled: form.elements.enabled.checked,
    };
    const finish = (response) => {
      saving = false;
      if (!response.ok) {
        return detailMessage(response, "The slide could not be saved.").then((message) => setStatus(status, message));
      }
      setStatus(status, "The slide was saved.");
      closeForm();
      return load();
    };
    if (!editingId) {
      const body = new FormData();
      body.append("image", selectedFile);
      body.append("title", fields.title);
      body.append("message", fields.message);
      body.append("display_order", String(fields.display_order));
      body.append("enabled", fields.enabled ? "true" : "false");
      api("/api/v1/admin/carousel", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfFromCookie() },
        body,
      }).then(finish).catch(() => {
        saving = false;
        setStatus(status, "The slide could not be saved.");
      });
      return;
    }
    api("/api/v1/admin/carousel/" + editingId, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfFromCookie() },
      body: JSON.stringify(fields),
    }).then((response) => {
      if (!response.ok || !selectedFile) {
        return finish(response);
      }
      const body = new FormData();
      body.append("image", selectedFile);
      return api("/api/v1/admin/carousel/" + editingId + "/image", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfFromCookie() },
        body,
      }).then(finish);
    }).catch(() => {
      saving = false;
      setStatus(status, "The slide could not be saved.");
    });
  });

  requireOwner().then((owner) => {
    if (owner) {
      load();
    }
  });
})();
