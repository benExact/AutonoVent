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

  const pendingKey = "autonovent-checkout-pending";
  let catalogue = [];
  let quote = null;
  let checkoutMode = "unavailable";

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
      name: String(data.get("customer_name") || ""),
      line1: String(data.get("line1") || ""),
      line2: String(data.get("line2") || "") || null,
      local_area: String(data.get("local_area") || ""),
      city: String(data.get("city") || ""),
      region: String(data.get("region") || ""),
      postal_code: String(data.get("postal_code") || ""),
      country: String(data.get("country") || "ZA"),
    };
  }

  function linePayload() {
    return window.AutonoventCart.read().map((line) => ({
      product_id: line.productId,
      quantity: line.quantity,
    }));
  }

  function cartSignature() {
    return JSON.stringify(window.AutonoventCart.read().map((line) => [line.productId, line.quantity]).sort());
  }

  function readPending() {
    try {
      const saved = JSON.parse(window.sessionStorage.getItem(pendingKey) || "null");
      if (!saved || saved.signature !== cartSignature() || typeof saved.key !== "string") {
        return null;
      }
      return saved;
    } catch (error) {
      return null;
    }
  }

  function orderKey() {
    const saved = readPending();
    if (saved) {
      return saved.key;
    }
    const key = window.crypto.randomUUID().replace(/-/g, "").slice(0, 32);
    window.sessionStorage.setItem(pendingKey, JSON.stringify({ signature: cartSignature(), key: key, order: null }));
    return key;
  }

  function rememberOrder(order) {
    const saved = readPending() || { signature: cartSignature(), key: orderKey() };
    saved.order = order;
    saved.signature = cartSignature();
    window.sessionStorage.setItem(pendingKey, JSON.stringify(saved));
  }

  function quantityControl(line, productId) {
    const controls = document.createElement("div");
    controls.className = "button-row";
    const decrease = document.createElement("button");
    decrease.type = "button";
    decrease.className = "button button--secondary";
    decrease.textContent = "Decrease";
    decrease.addEventListener("click", () => {
      window.AutonoventCart.setQuantity(productId, line.quantity - 1);
      quote = null;
      quoteHost.replaceChildren();
      renderCart();
    });
    const increase = document.createElement("button");
    increase.type = "button";
    increase.className = "button button--secondary";
    increase.textContent = "Increase";
    increase.disabled = line.quantity >= 20;
    increase.addEventListener("click", () => {
      window.AutonoventCart.setQuantity(productId, line.quantity + 1);
      quote = null;
      quoteHost.replaceChildren();
      renderCart();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "button button--secondary";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      window.AutonoventCart.remove(productId);
      quote = null;
      quoteHost.replaceChildren();
      renderCart();
    });
    controls.append(decrease, increase, remove);
    return controls;
  }

  function renderCart() {
    cartHost.replaceChildren();
    const lines = window.AutonoventCart.read();
    if (!lines.length) {
      setStatus("Your cart is empty. Add a listed product from the shop.");
      form.hidden = true;
      form.style.display = "none";
      return;
    }
    const list = document.createElement("ul");
    list.className = "catalogue-list";
    let subtotal = 0;
    let priced = true;
    lines.forEach((line) => {
      const product = catalogue.find((item) => item.id === line.productId);
      const row = document.createElement("li");
      const name = document.createElement("h2");
      name.textContent = product ? product.name : "This product is not listed for purchase.";
      const quantity = document.createElement("p");
      quantity.textContent = "Quantity " + line.quantity;
      row.append(name, quantity);
      if (product && Number.isInteger(product.unit_price_cents)) {
        subtotal += product.unit_price_cents * line.quantity;
        const price = document.createElement("p");
        price.className = "catalogue-price";
        price.textContent = money(product.unit_price_cents, product.currency) + (product.price_is_demo ? " each. Test price — not a confirmed selling price." : " each.");
        row.append(price);
      } else {
        priced = false;
      }
      row.append(quantityControl(line, line.productId));
      list.append(row);
    });
    cartHost.append(list);
    if (priced) {
      const total = document.createElement("p");
      total.className = "catalogue-price";
      total.textContent = "Cart subtotal " + money(subtotal, "ZAR") + ". The server calculates the order total after the delivery quote.";
      cartHost.append(total);
    }
    form.hidden = false;
    form.style.display = "";
    setStatus(checkoutMode === "sandbox"
      ? "Enter your contact details and a South African delivery address, then request a ShipLogic sandbox quote."
      : "Enter your contact details and a South African delivery address, then request a simulated delivery quote.");
  }

  function renderQuote(body) {
    quote = body;
    quoteHost.replaceChildren();
    const summary = document.createElement("p");
    summary.textContent = "Product subtotal " + money(body.subtotal_cents, body.currency) + ". " + body.label;
    quoteHost.append(summary);
    body.lines.forEach((line) => {
      const row = document.createElement("p");
      row.textContent = line.quantity + " × " + line.product_name + " at " + money(line.unit_price_cents, body.currency) + " = " + money(line.line_total_cents, body.currency) + (line.price_is_demo ? ". Test price — not a confirmed selling price." : "");
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
      setStatus(checkoutMode === "sandbox"
        ? "PayFast confirmed this sandbox payment. It is not a live sale."
        : "Simulated payment succeeded. This order is test data and is not a PayFast payment.");
      const done = document.createElement("a");
      done.className = "button button--primary";
      done.href = "products.html";
      done.textContent = "Back to the shop";
      done.addEventListener("click", () => {
        window.AutonoventCart.write([]);
        window.sessionStorage.removeItem(pendingKey);
      });
      paymentHost.append(done);
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
    if (checkoutMode === "sandbox") {
      const returned = new URLSearchParams(window.location.search).get("payment");
      if (returned === "return") {
        setStatus("You have returned from PayFast. This order stays unpaid until the sandbox notification is verified.");
      } else if (returned === "cancel") {
        setStatus("The PayFast sandbox payment was cancelled. The order is not paid.");
      } else {
        setStatus("Opening the PayFast sandbox. Returning to this page does not confirm payment.");
        startPayfast(order.id);
      }
      return;
    }
    paymentHost.append(actions);
    setStatus("Choose a simulated payment result. A failed or cancelled payment does not mark the order paid.");
  }

  function startPayfast(orderId) {
    csrf()
      .then((token) => post("/api/v1/checkout/orders/" + orderId + "/payfast", {}, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body || body.action !== "https://sandbox.payfast.co.za/eng/process" || !body.fields) {
          setStatus(detailMessage(body));
          return;
        }
        const redirect = document.createElement("form");
        redirect.method = "post";
        redirect.action = body.action;
        Object.keys(body.fields).forEach((name) => {
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = name;
          input.value = body.fields[name];
          redirect.append(input);
        });
        document.body.append(redirect);
        redirect.submit();
      })
      .catch(() => setStatus("The PayFast sandbox could not be opened. The order is not paid."));
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
        rememberOrder(body);
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
    setStatus(checkoutMode === "sandbox" ? "Requesting ShipLogic sandbox delivery quotes." : "Requesting simulated delivery quotes.");
    csrf()
      .then((token) => post("/api/v1/checkout/quotes", { delivery: deliveryPayload(), lines: linePayload() }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          setStatus(detailMessage(body));
          return;
        }
        renderQuote(body);
        if (!body.quotes || !body.quotes.length) {
          setStatus("No priced delivery option was returned. No delivery price has been estimated.");
          return;
        }
        setStatus(checkoutMode === "sandbox"
          ? "Select a ShipLogic sandbox option. The total is calculated by the server."
          : "Select a simulated delivery option. The total is calculated by the server.");
      })
      .catch(() => setStatus(checkoutMode === "sandbox" ? "ShipLogic sandbox quotes could not be loaded." : "Simulated delivery quotes could not be loaded."));
  });

  const draftKey = "autonovent-checkout-draft";
  const termsBox = form.querySelector("[data-accept-terms]");
  const placeButton = form.querySelector("[data-place-order]");

  function saveDraft() {
    const data = new FormData(form);
    const draft = {};
    data.forEach((value, key) => {
      draft[key] = String(value);
    });
    draft.accept_terms = termsBox && termsBox.checked ? "yes" : "";
    window.sessionStorage.setItem(draftKey, JSON.stringify(draft));
  }

  function restoreDraft() {
    try {
      const draft = JSON.parse(window.sessionStorage.getItem(draftKey) || "null");
      if (!draft) {
        return;
      }
      Object.keys(draft).forEach((key) => {
        const control = form.elements[key];
        if (!control || key === "accept_terms") {
          return;
        }
        control.value = draft[key];
      });
      if (termsBox) {
        termsBox.checked = draft.accept_terms === "yes";
      }
    } catch (error) {
      window.sessionStorage.removeItem(draftKey);
    }
  }

  function syncTerms() {
    if (placeButton && termsBox) {
      placeButton.disabled = !termsBox.checked;
    }
  }

  restoreDraft();
  syncTerms();
  form.addEventListener("input", saveDraft);
  form.addEventListener("change", () => {
    saveDraft();
    syncTerms();
  });
  if (window.AutonoventAddressSearch) {
    window.AutonoventAddressSearch.attach(form, { endpoint: endpoint });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const selected = selectedQuote();
    if (!quote || !selected) {
      setStatus(checkoutMode === "sandbox" ? "Request and select a ShipLogic sandbox quote first." : "Request and select a simulated delivery quote first.");
      return;
    }
    if (!termsBox || !termsBox.checked) {
      setStatus(checkoutMode === "sandbox" ? "Accept the Terms and Conditions before the PayFast sandbox payment." : "Accept the Terms and Conditions before the simulated payment.");
      if (termsBox) {
        termsBox.focus();
      }
      return;
    }
    const key = orderKey();
    const data = new FormData(form);
    const submitButton = form.querySelector("[data-place-order]");
    if (submitButton) {
      submitButton.disabled = true;
    }
    setStatus(checkoutMode === "sandbox" ? "Saving the order before the PayFast sandbox payment." : "Placing the simulated order.");
    csrf()
      .then((token) => post("/api/v1/checkout/orders", {
        idempotency_key: key,
        customer_name: String(data.get("customer_name") || ""),
        customer_email: String(data.get("customer_email") || ""),
        customer_phone: String(data.get("customer_phone") || ""),
        delivery: deliveryPayload(),
        lines: linePayload(),
        service_code: selected.service_code,
        expected_shipping_cents: selected.shipping_cents,
        accept_terms: true,
        terms_version: String(data.get("terms_version") || ""),
      }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok) {
          setStatus(detailMessage(body));
          if (submitButton) {
            submitButton.disabled = false;
          }
          if (response.status === 409) {
            window.sessionStorage.removeItem(pendingKey);
          }
          return;
        }
        form.hidden = true;
        form.style.display = "none";
        rememberOrder(body);
        renderPayment(body);
      })
      .catch(() => setStatus(checkoutMode === "sandbox" ? "The order could not be saved." : "The simulated order could not be placed."));
  });

  if (!endpoint) {
    setStatus("The checkout service is not configured.");
    return;
  }

  fetch(endpoint + "/api/v1/checkout/status", { headers: { Accept: "application/json" } })
    .then((response) => response.json())
    .then((body) => {
      checkoutMode = body && (body.checkout_mode === "sandbox" || body.checkout_mode === "simulation") ? body.checkout_mode : "unavailable";
      if (checkoutMode === "unavailable") {
        setStatus("Checkout is not enabled.");
        return;
      }
      const quoteButton = document.querySelector("[data-quote-button]");
      const placeButtonLabel = document.querySelector("[data-place-order]");
      const paymentNote = document.querySelector("[data-payment-note]");
      if (checkoutMode === "sandbox") {
        if (quoteButton) {
          quoteButton.textContent = "Get ShipLogic sandbox quotes";
        }
        if (placeButtonLabel) {
          placeButtonLabel.textContent = "Continue to PayFast sandbox";
        }
        if (paymentNote) {
          paymentNote.textContent = "This continues to the PayFast sandbox. Returning from PayFast does not mark the order paid. Read the Privacy Notice before you continue.";
        }
      }
      return fetch(endpoint + "/api/v1/products", { headers: { Accept: "application/json" } })
        .then((response) => response.json())
        .then((products) => {
          catalogue = products && Array.isArray(products.products) ? products.products : [];
          const pending = readPending();
          if (pending && pending.order) {
            form.hidden = true;
            form.style.display = "none";
            renderPayment(pending.order);
            return;
          }
          renderCart();
        });
    })
    .catch(() => setStatus("Simulated checkout could not be loaded."));
})();
