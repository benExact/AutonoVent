/* Owner product records and the checkout checklist. The session cookie is not read here. */

(function () {
  const logout = document.querySelector("[data-auth-logout]");
  const authStatus = document.querySelector("[data-auth-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!logout || !authStatus || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  let editingId = "";

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
    const list = document.createElement("div");
    list.className = "owner-table";
    products.forEach((product) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "owner-row";
      const name = document.createElement("strong");
      name.textContent = product.name;
      const price = document.createElement("span");
      price.textContent = money(product.unit_price_cents);
      const state = document.createElement("span");
      state.textContent = product.active ? "Active" : "Inactive";
      button.append(name, price, state);
      button.addEventListener("click", () => fillForm(product));
      list.append(button);
    });
    host.append(list);
  }

  function fillForm(product) {
    const form = document.querySelector("[data-product-form]");
    const heading = document.querySelector("[data-product-form-heading]");
    if (!form || !heading) {
      return;
    }
    editingId = product.id;
    heading.textContent = "Edit product";
    form.name.value = product.name;
    form.slug.value = product.slug;
    form.description.value = product.description || "";
    form.sku.value = product.sku || "";
    form.unit_price_cents.value = Number.isInteger(product.unit_price_cents) ? String(product.unit_price_cents) : "";
    form.currency.value = "ZAR";
    form.active.checked = product.active === true;
    setStatus(document.querySelector("[data-product-save]"), "");
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
    if (!form || !heading) {
      return;
    }
    editingId = "";
    heading.textContent = "New product";
    form.reset();
    form.currency.value = "ZAR";
    setStatus(document.querySelector("[data-product-save]"), "");
    const history = document.querySelector("[data-product-audit]");
    if (history) {
      history.replaceChildren();
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

  function centsFromForm(value) {
    const trimmed = value.trim();
    if (!trimmed) {
      return null;
    }
    if (!/^[0-9]+$/.test(trimmed)) {
      throw new Error("Enter the selling price as a whole number of cents, or leave it empty.");
    }
    return Number(trimmed);
  }

  function bindProductForm() {
    const form = document.querySelector("[data-product-form]");
    const clear = document.querySelector("[data-product-clear]");
    const result = document.querySelector("[data-product-save]");
    if (!form || !clear) {
      return;
    }
    clear.addEventListener("click", clearForm);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      let cents;
      try {
        cents = centsFromForm(form.unit_price_cents.value);
      } catch (error) {
        setStatus(result, error.message);
        return;
      }
      const body = {
        name: form.name.value,
        slug: form.slug.value,
        description: form.description.value,
        sku: form.sku.value,
        unit_price_cents: cents,
        currency: "ZAR",
        active: form.active.checked,
      };
      const path = editingId ? "/api/v1/admin/products/" + encodeURIComponent(editingId) : "/api/v1/admin/products";
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
        const saved = await response.json();
        setStatus(result, "Saved.");
        fillForm(saved);
        loadProducts();
      }).catch(() => {
        setStatus(result, "The product service could not be reached.");
      });
    });
  }

  function renderReadiness(report) {
    const host = document.querySelector("[data-readiness-list]");
    const status = document.querySelector("[data-readiness-status]");
    if (!host || !status) {
      return;
    }
    host.replaceChildren();
    if (report.checkout_simulation_enabled) {
      setStatus(status, "Simulated checkout is enabled on this development server. Orders placed there are test data. Real checkout is not enabled.");
    } else {
      setStatus(status, report.checkout_enabled ? "" : "Checkout is not enabled.");
    }
    report.items.forEach((item) => {
      const row = document.createElement("li");
      const name = document.createElement("strong");
      name.textContent = item.label;
      const state = document.createElement("span");
      state.textContent = item.ready ? "Ready" : "Missing";
      const detail = document.createElement("p");
      detail.textContent = item.detail;
      row.append(name, state, detail);
      host.append(row);
    });
  }

  function loadReadiness() {
    const status = document.querySelector("[data-readiness-status]");
    const retry = document.querySelector("[data-readiness-retry]");
    setStatus(status, "Loading checklist.");
    if (retry) {
      retry.hidden = true;
    }
    api("/api/v1/admin/readiness").then(async (response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (!response.ok) {
        setStatus(status, "The checklist could not be loaded.");
        if (retry) {
          retry.hidden = false;
        }
        return;
      }
      renderReadiness(await response.json());
    }).catch(() => {
      setStatus(status, "The checklist could not be loaded.");
      if (retry) {
        retry.hidden = false;
      }
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
    if (document.querySelector("[data-readiness-list]")) {
      const retry = document.querySelector("[data-readiness-retry]");
      if (retry) {
        retry.addEventListener("click", loadReadiness);
      }
      loadReadiness();
    }
  }).catch(() => {
    setStatus(authStatus, "The sign-in service could not be reached.");
  });
})();
