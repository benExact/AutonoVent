/* Simulated checkout. Amounts shown after a quote come from the server response. */

(function () {
  const status = document.querySelector("[data-checkout-status]");
  const cartHost = document.querySelector("[data-checkout-cart]");
  const form = document.querySelector("[data-checkout-form]");
  const quoteHost = document.querySelector("[data-quote-options]");
  const paymentHost = document.querySelector("[data-checkout-payment]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;
  const endpoint = typeof baseUrl === "string" ? baseUrl.replace(/\/$/, "") : "";

  if (!status || !cartHost || !form || !quoteHost || !paymentHost || !window.AutonoventCart) {
    return;
  }

  let catalogue = [];
  let quote = null;
  let orderKey = "";

  function money(cents, currency) {
    try {
      return new Intl.NumberFormat("en-ZA", { style: "currency", currency: currency || "ZAR" }).format(cents / 100);
    } catch (error) {
      return "";
    }
  }

  function setStatus(message) {
    status.textContent = message;
  }

  function detailMessage(body) {
    if (!body) {
      return "The request could not be completed.";
    }
    if (typeof body.detail === "string") {
      return body.detail;
    }
    return "Check the address and try again.";
  }

  function csrf() {
    return fetch(endpoint + "/api/v1/auth/csrf", { credentials: "include", headers: { Accept: "application/json" } })
      .then((response) => response.json())
      .then((body) => body.csrf_token || "");
  }

  function post(path, payload, token) {
    return fetch(endpoint + path, {
      method: "POST",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": token,
      },
      body: JSON.stringify(payload),
    });
  }

  function deliveryPayload() {
    const data = new FormData(form);
    return {
      name: String(data.get("delivery_name") || ""),
      line1: String(data.get("line1") || ""),
      line2: String(data.get("line2") || "") || null,
      city: String(data.get("city") || ""),
      region: String(data.get("region") || ""),
      postal_code: String(data.get("postal_code") || ""),
      country: "ZA",
    };
  }

  function linePayload() {
    return window.AutonoventCart.read().map((line) => ({
      product_id: line.productId,
      quantity: line.quantity,
    }));
  }

  function renderCart() {
    cartHost.replaceChildren();
    const lines = window.AutonoventCart.read();
    if (!lines.length) {
      setStatus("The simulated cart is empty. Add a listed product from the product page.");
      form.hidden = true;
      form.style.display = "none";
      return;
    }
    const list = document.createElement("ul");
    list.className = "catalogue-list";
    lines.forEach((line) => {
      const product = catalogue.find((item) => item.id === line.productId);
      const row = document.createElement("li");
      const name = document.createElement("h2");
      name.textContent = product ? product.name : "This product is not listed for purchase.";
      const quantity = document.createElement("p");
      quantity.textContent = "Quantity " + line.quantity;
      row.append(name, quantity);
      if (product && Number.isInteger(product.unit_price_cents)) {
        const price = document.createElement("p");
        price.className = "catalogue-price";
        price.textContent = money(product.unit_price_cents, product.currency) + " each, from the catalogue";
        row.append(price);
      }
      list.append(row);
    });
    cartHost.append(list);
    form.hidden = false;
    form.style.display = "";
    setStatus("Enter a South African delivery address, then request a simulated delivery quote.");
  }

  function renderQuote(body) {
    quote = body;
    quoteHost.replaceChildren();
    const summary = document.createElement("p");
    summary.textContent = "Product subtotal " + money(body.subtotal_cents, body.currency) + ". " + body.label;
    quoteHost.append(summary);
    body.lines.forEach((line) => {
      const row = document.createElement("p");
      row.textContent = line.quantity + " × " + line.product_name + " at " + money(line.unit_price_cents, body.currency) + " = " + money(line.line_total_cents, body.currency);
      quoteHost.append(row);
    });
    body.quotes.forEach((option) => {
      const wrapper = document.createElement("label");
      wrapper.className = "field";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "service_code";
      input.value = option.service_code;
      input.required = true;
      input.dataset.shippingCents = String(option.shipping_cents);
      const text = document.createElement("span");
      text.textContent = option.service_name + " — delivery " + money(option.shipping_cents, body.currency) + ", total " + money(option.total_cents, body.currency) + ". " + option.label;
      wrapper.append(input, text);
      quoteHost.append(wrapper);
    });
  }

  function selectedQuote() {
    const selected = form.querySelector("input[name='service_code']:checked");
    if (!selected) {
      return null;
    }
    return {
      service_code: selected.value,
      shipping_cents: Number(selected.dataset.shippingCents),
    };
  }

  function renderPayment(order) {
    paymentHost.replaceChildren();
    const summary = document.createElement("div");
    summary.className = "notice";
    const title = document.createElement("p");
    title.textContent = order.label + " " + order.order_number;
    const amounts = document.createElement("p");
    amounts.textContent = "Subtotal " + money(order.subtotal_cents, order.currency) + ". Delivery " + money(order.shipping_cents, order.currency) + ". Total " + money(order.total_cents, order.currency) + ".";
    const payment = document.createElement("p");
    payment.textContent = "Payment " + order.payment_status + ". Fulfilment " + order.fulfilment_status + ". " + order.payment_label;
    if (order.payment_reference) {
      const reference = document.createElement("p");
      reference.textContent = "Payment reference " + order.payment_reference + ".";
      summary.append(title, amounts, payment, reference);
    } else {
      summary.append(title, amounts, payment);
    }
    paymentHost.append(summary);
    if (order.payment_status === "paid") {
      setStatus("Simulated payment succeeded. This order is test data and is not a PayFast payment.");
      return;
    }
    const actions = document.createElement("div");
    actions.className = "button-row";
    [
      ["success", "Simulate successful payment"],
      ["failure", "Simulate failed payment"],
      ["cancel", "Cancel simulated payment"],
    ].forEach((pair) => {
      const button = document.createElement("button");
      button.className = pair[0] === "success" ? "button button--primary" : "button button--secondary";
      button.type = "button";
      button.textContent = pair[1];
      button.addEventListener("click", () => pay(order.id, pair[0], button));
      actions.append(button);
    });
    paymentHost.append(actions);
    setStatus("Choose a simulated payment result. A failed or cancelled payment does not mark the order paid.");
  }

  function pay(orderId, outcome, button) {
    const storageKey = "autonovent-simulated-payment-" + orderId + "-" + outcome;
    let key = window.sessionStorage.getItem(storageKey);
    if (!key) {
      key = window.crypto.randomUUID() + window.crypto.randomUUID();
      key = key.replace(/-/g, "").slice(0, 32);
      window.sessionStorage.setItem(storageKey, key);
    }
    button.disabled = true;
    csrf()
      .then((token) => post("/api/v1/checkout/orders/" + orderId + "/payment", { outcome: outcome, idempotency_key: key }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          setStatus(detailMessage(body));
          button.disabled = false;
          return;
        }
        renderPayment(body);
      })
      .catch(() => {
        setStatus("The simulated payment could not be reached.");
        button.disabled = false;
      });
  }

  form.addEventListener("input", (event) => {
    if (event.target && event.target.name === "service_code") {
      return;
    }
    quote = null;
    quoteHost.replaceChildren();
  });

  document.querySelector("[data-quote-button]").addEventListener("click", () => {
    if (!form.reportValidity()) {
      return;
    }
    setStatus("Requesting simulated delivery quotes.");
    csrf()
      .then((token) => post("/api/v1/checkout/quotes", { delivery: deliveryPayload(), lines: linePayload() }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          setStatus(detailMessage(body));
          return;
        }
        renderQuote(body);
        setStatus("Select a simulated delivery option. The total is calculated by the server.");
      })
      .catch(() => setStatus("Simulated delivery quotes could not be loaded."));
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = selectedQuote();
    if (!quote || !selected) {
      setStatus("Request and select a simulated delivery quote first.");
      return;
    }
    if (!orderKey) {
      orderKey = window.crypto.randomUUID().replace(/-/g, "").slice(0, 32);
    }
    const data = new FormData(form);
    setStatus("Placing the simulated order.");
    csrf()
      .then((token) => post("/api/v1/checkout/orders", {
        idempotency_key: orderKey,
        customer_name: String(data.get("customer_name") || ""),
        customer_email: String(data.get("customer_email") || ""),
        customer_phone: String(data.get("customer_phone") || "") || null,
        delivery: deliveryPayload(),
        lines: linePayload(),
        service_code: selected.service_code,
        expected_shipping_cents: selected.shipping_cents,
      }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          setStatus(detailMessage(body));
          if (response.status === 409) {
            orderKey = "";
          }
          return;
        }
        form.hidden = true;
        form.style.display = "none";
        renderPayment(body);
      })
      .catch(() => setStatus("The simulated order could not be placed."));
  });

  if (!endpoint) {
    setStatus("The checkout service is not configured.");
    return;
  }

  fetch(endpoint + "/api/v1/checkout/status", { headers: { Accept: "application/json" } })
    .then((response) => response.json())
    .then((body) => {
      if (!body || body.simulation_enabled !== true) {
        setStatus("Simulated checkout is not enabled.");
        return;
      }
      return fetch(endpoint + "/api/v1/products", { headers: { Accept: "application/json" } })
        .then((response) => response.json())
        .then((products) => {
          catalogue = products && Array.isArray(products.products) ? products.products : [];
          renderCart();
        });
    })
    .catch(() => setStatus("Simulated checkout could not be loaded."));
})();
