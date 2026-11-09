/* Private owner orders. The session cookie is not read here. */

(function () {
  const logout = document.querySelector("[data-auth-logout]");
  const authStatus = document.querySelector("[data-auth-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!logout || !authStatus || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  const labels = {
    pending: "Pending",
    paid: "Paid",
    failed: "Failed",
    cancelled: "Cancelled",
    unfulfilled: "Unfulfilled",
    processing: "Processing",
    packed: "Packed",
    shipped: "Shipped",
    delivered: "Delivered",
    payment_status: "Payment",
    fulfilment_status: "Fulfilment",
  };

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

  function label(value) {
    return labels[value] || "Not recorded";
  }

  function money(cents, currency) {
    if (!Number.isInteger(cents)) {
      return "Not recorded";
    }
    return new Intl.NumberFormat("en-ZA", {
      style: "currency",
      currency: currency || "ZAR",
    }).format(cents / 100);
  }

  function when(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return "Not recorded";
    }
    return new Intl.DateTimeFormat("en-ZA", { dateStyle: "medium", timeStyle: "short" }).format(date);
  }

  function textOrMissing(value) {
    return typeof value === "string" && value.trim() ? value : "Not recorded";
  }

  function historyTable(caption, headers, rows) {
    const wrap = document.createElement("div");
    wrap.className = "history-table-wrap";
    const table = document.createElement("table");
    table.className = "history-table";
    const title = document.createElement("caption");
    title.className = "visually-hidden";
    title.textContent = caption;
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    headers.forEach((text) => {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = text;
      headRow.append(cell);
    });
    head.append(headRow);
    const body = document.createElement("tbody");
    rows.forEach((cells) => {
      const row = document.createElement("tr");
      cells.forEach((text) => {
        const cell = document.createElement("td");
        cell.textContent = text;
        row.append(cell);
      });
      body.append(row);
    });
    table.append(title, head, body);
    wrap.append(table);
    return wrap;
  }

  function api(path, options) {
    return fetch(endpoint + path, Object.assign({ credentials: "include", headers: { Accept: "application/json" } }, options));
  }

  function detailMessage(response) {
    return response.json().then(
      (body) => (typeof body.detail === "string" ? body.detail : "The order service could not be reached."),
      () => "The order service could not be reached."
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

  function renderSummary(summary) {
    const host = document.querySelector("[data-summary]");
    if (!host || !summary) {
      return;
    }
    const cards = [
      ["Orders", summary.orders],
      ["Payment pending", summary.payment.pending],
      ["Unfulfilled", summary.fulfilment.unfulfilled],
      ["Processing", summary.fulfilment.processing],
      ["Packed", summary.fulfilment.packed],
      ["Shipped", summary.fulfilment.shipped],
    ];
    host.replaceChildren();
    cards.forEach((card) => {
      const article = document.createElement("article");
      article.className = "owner-card";
      const name = document.createElement("p");
      name.className = "eyebrow";
      name.textContent = card[0];
      const value = document.createElement("p");
      value.className = "owner-card__value";
      value.textContent = String(card[1]);
      article.append(name, value);
      host.append(article);
    });
  }

  function downloadLink(orderId) {
    const link = document.createElement("a");
    link.className = "button button--secondary";
    link.href = endpoint + "/api/v1/orders/" + encodeURIComponent(orderId) + "/document";
    link.textContent = "Download PDF";
    return link;
  }

  function renderOrders(payload) {
    const host = document.querySelector("[data-orders-list]");
    const pages = document.querySelector("[data-orders-pages]");
    const status = document.querySelector("[data-orders-status]");
    if (!host || !pages || !status) {
      return;
    }
    host.replaceChildren();
    pages.replaceChildren();
    if (!payload.orders.length) {
      setStatus(status, "No orders have been recorded.");
      return;
    }
    setStatus(status, "");
    const table = document.createElement("div");
    table.className = "owner-table";
    payload.orders.forEach((order) => {
      const entry = document.createElement("div");
      entry.className = "owner-order";
      const link = document.createElement("a");
      link.className = "owner-row";
      link.href = "order.html?id=" + encodeURIComponent(order.id);
      const reference = document.createElement("strong");
      reference.textContent = order.is_simulation ? order.order_number + " · Simulated test order" : order.order_number;
      const customer = document.createElement("span");
      customer.textContent = order.customer_name;
      const fulfilment = document.createElement("span");
      fulfilment.textContent = label(order.fulfilment_status);
      const payment = document.createElement("span");
      payment.textContent = label(order.payment_status);
      const total = document.createElement("span");
      total.textContent = money(order.total_cents, order.currency);
      link.append(reference, customer, fulfilment, payment, total);
      entry.append(link, downloadLink(order.id));
      table.append(entry);
    });
    host.append(table);
    if (payload.offset > 0) {
      const previous = document.createElement("a");
      previous.href = "orders.html?offset=" + Math.max(payload.offset - payload.limit, 0);
      previous.textContent = "Previous";
      pages.append(previous);
    }
    if (payload.offset + payload.orders.length < payload.total) {
      const next = document.createElement("a");
      next.href = "orders.html?offset=" + (payload.offset + payload.limit);
      next.textContent = "Next";
      pages.append(next);
    }
  }

  function loadOrders() {
    const status = document.querySelector("[data-orders-status]");
    const retry = document.querySelector("[data-orders-retry]");
    const params = new URLSearchParams(window.location.search);
    const offset = params.get("offset") || "0";
    setStatus(status, "Loading orders.");
    if (retry) {
      retry.hidden = true;
    }
    Promise.all([
      api("/api/v1/orders/summary"),
      api("/api/v1/orders?limit=20&offset=" + encodeURIComponent(offset)),
    ]).then(async ([summaryResponse, listResponse]) => {
      if (summaryResponse.status === 401 || listResponse.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (!summaryResponse.ok || !listResponse.ok) {
        setStatus(status, "Orders could not be loaded.");
        if (retry) {
          retry.hidden = false;
        }
        return;
      }
      renderSummary(await summaryResponse.json());
      renderOrders(await listResponse.json());
    }).catch(() => {
      setStatus(status, "Orders could not be loaded.");
      if (retry) {
        retry.hidden = false;
      }
    });
  }

  function deliveryText(order) {
    const amount = money(order.shipping_cents, order.currency);
    if (order.shipping_provider === "simulated-courier") {
      return amount + " · Simulated courier. This is not a ShipLogic price. " + (order.shipping_service_code || "") + " " + (order.shipping_quote_reference || "");
    }
    if (order.shipping_provider === "bobgo") {
      return amount + " · Bob Go sandbox rate. This is not a live courier booking. " + (order.shipping_service_code || "") + " " + (order.shipping_quote_reference || "");
    }
    if (order.shipping_provider === "shiplogic") {
      return amount + " · ShipLogic sandbox rate. This is not a live courier booking. " + (order.shipping_service_code || "") + " " + (order.shipping_quote_reference || "");
    }
    return amount;
  }

  function paymentText(order) {
    const status = label(order.payment_status);
    if (order.is_simulation || order.payment_provider === "simulated") {
      return status + " · Simulated payment. This is not a PayFast payment.";
    }
    if (order.payment_provider === "payfast") {
      return status + " · PayFast sandbox. This is not a live payment.";
    }
    if (order.payment_provider) {
      return status + " · " + order.payment_provider;
    }
    return status;
  }

  function field(title, value) {
    const row = document.createElement("div");
    const name = document.createElement("dt");
    name.textContent = title;
    const item = document.createElement("dd");
    item.textContent = value;
    row.append(name, item);
    return row;
  }

  function renderDetail(order) {
    const host = document.querySelector("[data-order-detail]");
    const status = document.querySelector("[data-order-status]");
    if (!host || !status) {
      return;
    }
    document.title = "Autonovent | " + order.order_number;
    setStatus(status, "");
    host.replaceChildren();
    host.append(downloadLink(order.id));

    const facts = document.createElement("dl");
    facts.className = "owner-facts";
    const address = [order.delivery_name, order.delivery_line1, order.delivery_line2, order.delivery_suburb, order.delivery_city, order.delivery_region, order.delivery_postal_code, order.delivery_country]
      .filter((part) => typeof part === "string" && part.trim())
      .join(", ");
    [
      ["Order", order.is_simulation ? order.order_number + " · Simulated test order" : order.order_number],
      ["Created", when(order.created_at)],
      ["Customer", order.customer_name],
      ["Email", order.customer_email],
      ["Phone", textOrMissing(order.customer_phone)],
      ["Delivery", address || "Not recorded"],
      ["Subtotal", money(order.subtotal_cents, order.currency)],
      ["Delivery", deliveryText(order)],
      ["Total", money(order.total_cents, order.currency)],
      ["Payment", paymentText(order)],
      ["Payment reference", textOrMissing(order.payment_reference)],
      ["Terms", order.terms_accepted ? (order.terms_version || "Accepted") : "Not recorded"],
      ["Fulfilment", label(order.fulfilment_status)],
    ].forEach((pair) => facts.append(field(pair[0], pair[1])));
    host.append(facts);

    const itemsHeading = document.createElement("h2");
    itemsHeading.textContent = "Items";
    host.append(itemsHeading);
    if (!order.items.length) {
      const empty = document.createElement("p");
      empty.textContent = "No items are recorded.";
      host.append(empty);
    } else {
      const list = document.createElement("ul");
      list.className = "owner-items";
      order.items.forEach((item) => {
        const row = document.createElement("li");
        row.textContent = item.quantity + " × " + item.product_name + " (" + textOrMissing(item.sku) + ") — " + money(item.unit_price_cents, order.currency) + " each, " + money(item.line_total_cents, order.currency) + (item.price_is_demo ? ". Test price — not a confirmed selling price." : "");
        list.append(row);
      });
      host.append(list);
    }

    const updateHeading = document.createElement("h2");
    updateHeading.textContent = "Fulfilment";
    host.append(updateHeading);
    if (!order.allowed_fulfilment_statuses.length) {
      const done = document.createElement("p");
      done.textContent = "No further fulfilment change is available.";
      host.append(done);
    } else {
      const form = document.createElement("form");
      form.className = "enquiry-form";
      const wrapper = document.createElement("div");
      wrapper.className = "field";
      const name = document.createElement("label");
      name.htmlFor = "fulfilment-status";
      name.textContent = "Next status";
      const select = document.createElement("select");
      select.id = "fulfilment-status";
      select.name = "status";
      select.required = true;
      order.allowed_fulfilment_statuses.forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = label(value);
        select.append(option);
      });
      const button = document.createElement("button");
      button.className = "button button--primary";
      button.type = "submit";
      button.textContent = "Update fulfilment";
      const result = document.createElement("p");
      result.className = "form-status";
      result.setAttribute("role", "status");
      wrapper.append(name, select);
      form.append(wrapper, button, result);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        result.textContent = "Saving.";
        api("/api/v1/orders/" + encodeURIComponent(order.id) + "/fulfilment", {
          method: "PATCH",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfFromCookie(),
          },
          body: JSON.stringify({ status: select.value }),
        }).then(async (response) => {
          if (response.status === 401) {
            window.location.assign("login.html");
            return;
          }
          if (!response.ok) {
            result.textContent = await detailMessage(response);
            return;
          }
          renderDetail(await response.json());
        }).catch(() => {
          result.textContent = "The order service could not be reached.";
        });
      });
      host.append(form);
    }

    const historyHeading = document.createElement("h2");
    historyHeading.textContent = "Status history";
    host.append(historyHeading);
    const rows = (order.status_events || []).map((event) => [
      when(event.created_at),
      label(event.field_name),
      event.from_status ? label(event.from_status) : "—",
      label(event.to_status),
      textOrMissing(event.actor),
    ]);
    host.append(historyTable("Status history", ["When", "What", "From", "To", "Who"], rows));
  }

  function loadOrder() {
    const status = document.querySelector("[data-order-status]");
    const retry = document.querySelector("[data-order-retry]");
    const id = new URLSearchParams(window.location.search).get("id");
    if (!id) {
      setStatus(status, "Choose an order from the list.");
      return;
    }
    setStatus(status, "Loading order.");
    if (retry) {
      retry.hidden = true;
    }
    api("/api/v1/orders/" + encodeURIComponent(id)).then(async (response) => {
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (response.status === 404) {
        setStatus(status, "The order does not exist.");
        return;
      }
      if (!response.ok) {
        setStatus(status, "The order could not be loaded.");
        if (retry) {
          retry.hidden = false;
        }
        return;
      }
      renderDetail(await response.json());
    }).catch(() => {
      setStatus(status, "The order could not be loaded.");
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
    if (document.querySelector("[data-orders-list]")) {
      const retry = document.querySelector("[data-orders-retry]");
      if (retry) {
        retry.addEventListener("click", loadOrders);
      }
      loadOrders();
    }
    if (document.querySelector("[data-order-detail]")) {
      const retry = document.querySelector("[data-order-retry]");
      if (retry) {
        retry.addEventListener("click", loadOrder);
      }
      loadOrder();
    }
  }).catch(() => {
    setStatus(authStatus, "The sign-in service could not be reached.");
  });
})();
