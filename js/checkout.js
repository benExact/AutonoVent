/* Checkout. Amounts and payment status come from the server response. */

(function () {
  const flow = window.AutonoventCheckoutFlow;
  const status = document.querySelector("[data-checkout-status]");
  const form = document.querySelector("[data-checkout-form]");
  const quoteHost = document.querySelector("[data-quote-options]");
  const summaryHost = document.querySelector("[data-order-summary]");
  const paymentHost = document.querySelector("[data-checkout-payment]");
  const baseUrl = window.AUTONOVENT_API_BASE_URL;
  const endpoint = typeof baseUrl === "string" ? baseUrl.replace(/\/$/, "") : "";
  const addressNames = new Set(["line1", "line2", "local_area", "city", "region", "postal_code", "country"]);

  if (!flow || !status || !form || !quoteHost || !summaryHost || !paymentHost || !window.AutonoventCart) {
    return;
  }

  const pendingKey = "autonovent-checkout-pending";
  const scheduler = flow.createQuoteScheduler(flow.debounceMs);
  const submitLock = flow.createSubmitLock();
  const clock = {
    later: function (delay, fn) { return window.setTimeout(fn, delay); },
    clear: function (timer) { window.clearTimeout(timer); },
  };
  let catalogue = [];
  let quote = null;
  let quoteKey = "";
  let quoteFetchedAt = 0;
  let quoteRequest = 0;
  let inFlightKey = "";
  let selectedCode = "";
  let checkoutMode = "unavailable";
  let shippingQuotes = "";

  function money(cents) {
    try {
      return new Intl.NumberFormat("en-ZA", { style: "currency", currency: "ZAR" }).format(cents / 100);
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

  function readAddress() {
    const data = new FormData(form);
    return {
      line1: String(data.get("line1") || ""),
      line2: String(data.get("line2") || ""),
      local_area: String(data.get("local_area") || ""),
      city: String(data.get("city") || ""),
      region: String(data.get("region") || ""),
      postal_code: String(data.get("postal_code") || ""),
      country: String(data.get("country") || "ZA"),
    };
  }

  function recipientName() {
    const data = new FormData(form);
    return flow.customerName(data.get("given_name"), data.get("family_name"));
  }

  function deliveryPayload() {
    const address = readAddress();
    return {
      name: recipientName() || "Customer",
      line1: address.line1,
      line2: address.line2 || null,
      local_area: address.local_area,
      city: address.city,
      region: address.region,
      postal_code: address.postal_code,
      country: address.country || "ZA",
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

  function quoteAge() {
    return quote ? Date.now() - quoteFetchedAt : flow.quoteLifetimeMs;
  }

  function selectedOption() {
    if (!quote || !selectedCode) {
      return null;
    }
    return quote.quotes.find((option) => option.service_code === selectedCode) || null;
  }

  function selectedQuote() {
    const option = selectedOption();
    if (!option) {
      return null;
    }
    return { service_code: option.service_code, shipping_cents: option.shipping_cents };
  }

  function clearQuote() {
    quote = null;
    quoteKey = "";
    quoteFetchedAt = 0;
    selectedCode = "";
    quoteHost.replaceChildren();
    quoteHost.removeAttribute("aria-busy");
  }

  function renderSummary() {
    summaryHost.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = "Order summary";
    summaryHost.append(heading);
    const lines = window.AutonoventCart.read();
    if (!lines.length) {
      const empty = document.createElement("p");
      empty.textContent = "Your cart is empty.";
      summaryHost.append(empty);
      return;
    }
    let subtotal = 0;
    lines.forEach((line) => {
      const quoted = quote && quote.lines.find((item) => item.product_id === line.productId);
      const product = catalogue.find((item) => item.id === line.productId);
      const row = document.createElement("div");
      row.className = "checkout-line";
      const name = document.createElement("p");
      const label = quoted ? quoted.product_name : (product ? product.name : "This product is not listed for purchase.");
      name.textContent = label;
      row.append(name);
      const unit = quoted ? quoted.unit_price_cents : (product ? product.unit_price_cents : null);
      if (Number.isInteger(unit)) {
        subtotal += unit * line.quantity;
        const price = document.createElement("p");
        price.textContent = line.quantity + " × " + money(unit);
        row.append(price);
      }
      row.append(window.AutonoventCart.lineControls(line.productId, line.quantity, () => {
        quoteRequest += 1;
        clearQuote();
        renderSummary();
        scheduleRates();
      }));
      summaryHost.append(row);
    });
    const option = selectedOption();
    const totals = flow.displayTotal(quote ? quote.subtotal_cents : subtotal, option);
    const delivery = document.createElement("p");
    if (option) {
      delivery.textContent = option.service_name + " delivery " + money(option.shipping_cents) + ", VAT inclusive.";
    } else {
      delivery.textContent = "Delivery is not selected.";
    }
    const total = document.createElement("p");
    total.className = "checkout-total";
    total.textContent = totals.totalCents === null ? "Total " + money(totals.subtotalCents) + " before delivery." : "Total " + money(totals.totalCents);
    summaryHost.append(delivery, total);
  }

  function renderRates(body) {
    quote = body;
    quoteHost.replaceChildren();
    if (!body.quotes || !body.quotes.length) {
      const empty = document.createElement("p");
      empty.textContent = "No delivery rates are available for this address.";
      quoteHost.append(empty, retryButton());
      renderSummary();
      return;
    }
    body.quotes.forEach((option) => {
      const card = document.createElement("label");
      card.className = "quote-card";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "service_code";
      input.value = option.service_code;
      input.checked = option.service_code === selectedCode;
      const name = document.createElement("strong");
      name.textContent = option.service_name;
      const price = document.createElement("span");
      price.className = "quote-price";
      price.textContent = money(option.shipping_cents) + " VAT inclusive";
      card.append(input, name, price);
      const estimate = flow.deliveryEstimate(option);
      if (estimate) {
        const when = document.createElement("span");
        when.textContent = "Delivery window " + estimate + ".";
        card.append(when);
      }
      quoteHost.append(card);
    });
    if (selectedCode && !body.quotes.some((option) => option.service_code === selectedCode)) {
      selectedCode = "";
      setStatus("The previous delivery option is no longer available. Choose one of the current rates.");
    }
    if (body.label) {
      const note = document.createElement("p");
      note.className = "field-note";
      note.textContent = body.label;
      quoteHost.append(note);
    }
    renderSummary();
  }

  function retryButton() {
    const button = document.createElement("button");
    button.className = "button button--secondary checkout-retry";
    button.type = "button";
    button.textContent = "Try delivery rates again";
    button.addEventListener("click", () => requestRates(true));
    return button;
  }

  function showRateError(message) {
    clearQuote();
    const text = document.createElement("p");
    text.textContent = message;
    quoteHost.append(text, retryButton());
    renderSummary();
  }

  function requestRates(force) {
    const address = readAddress();
    const key = flow.addressKey(address, linePayload());
    const decision = flow.quoteDecision({
      valid: flow.addressIsValid(address),
      key: key,
      quotedKey: quoteKey,
      ageMs: quoteAge(),
      inFlightKey: inFlightKey,
    });
    if (!force && decision !== "request") {
      return;
    }
    if (!flow.addressIsValid(address)) {
      return;
    }
    const requestId = quoteRequest + 1;
    quoteRequest = requestId;
    inFlightKey = key;
    quoteHost.setAttribute("aria-busy", "true");
    setStatus(shippingQuotes === "shiplogic" ? "Checking ShipLogic sandbox delivery rates." : "Checking delivery rates.");
    csrf()
      .then((token) => post("/api/v1/checkout/quotes", { delivery: deliveryPayload(), lines: linePayload() }, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (requestId !== quoteRequest) {
          return;
        }
        if (!response.ok) {
          showRateError(detailMessage(body));
          return;
        }
        quoteKey = key;
        quoteFetchedAt = Date.now();
        renderRates(body);
        quoteHost.removeAttribute("aria-busy");
        if (!body.quotes || !body.quotes.length) {
          setStatus("No delivery rates are available for this address. No delivery price has been estimated.");
          return;
        }
        setStatus("Choose a delivery option. The server checks the price again before payment.");
      })
      .catch(() => {
        if (requestId !== quoteRequest) {
          return;
        }
        showRateError(shippingQuotes === "shiplogic"
          ? "ShipLogic sandbox rates could not be loaded. No delivery price has been estimated."
          : "Delivery rates could not be loaded. No delivery price has been estimated.");
      })
      .finally(() => {
        if (inFlightKey === key) {
          inFlightKey = "";
        }
      });
  }

  function scheduleRates() {
    scheduler.push(() => requestRates(false), clock);
  }

  function releasePay() {
    submitLock.release();
    const button = form.querySelector("[data-place-order]");
    if (button) {
      button.disabled = false;
      button.textContent = "Pay Now";
    }
  }

  function renderPayment(order) {
    paymentHost.replaceChildren();
    const summary = document.createElement("div");
    summary.className = "notice";
    const title = document.createElement("p");
    title.textContent = order.label + " " + order.order_number;
    const amounts = document.createElement("p");
    amounts.textContent = "Subtotal " + money(order.subtotal_cents) + ". Delivery " + money(order.shipping_cents) + ". Total " + money(order.total_cents) + ".";
    const payment = document.createElement("p");
    payment.textContent = "Payment " + order.payment_status + ". Fulfilment " + order.fulfilment_status + ". " + order.payment_label;
    summary.append(title, amounts, payment);
    if (order.payment_reference) {
      const reference = document.createElement("p");
      reference.textContent = "Payment reference " + order.payment_reference + ".";
      summary.append(reference);
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
      const retry = document.createElement("button");
      retry.className = "button button--secondary";
      retry.type = "button";
      retry.textContent = "Open PayFast sandbox again";
      retry.addEventListener("click", () => startPayfast(order.id));
      paymentHost.append(retry);
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

  function startPayfast(orderId) {
    csrf()
      .then((token) => post("/api/v1/checkout/orders/" + orderId + "/payfast", {}, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body || !flow.payfastActionAllowed(body.action) || !body.fields) {
          setStatus(detailMessage(body) || "PayFast sandbox is not available. The order is not paid.");
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

  const draftKey = "autonovent-checkout-draft";
  const termsBox = form.querySelector("[data-accept-terms]");

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

  function onAddressEdited() {
    quoteRequest += 1;
    clearQuote();
    renderSummary();
    scheduleRates();
  }

  form.addEventListener("input", (event) => {
    saveDraft();
    const name = event.target && event.target.name;
    if (name === "service_code") {
      selectedCode = event.target.value;
      renderSummary();
      return;
    }
    if (addressNames.has(name)) {
      onAddressEdited();
    }
  });

  form.addEventListener("change", (event) => {
    saveDraft();
    const name = event.target && event.target.name;
    if (name === "service_code") {
      selectedCode = event.target.value;
      renderSummary();
      return;
    }
    if (addressNames.has(name)) {
      onAddressEdited();
    }
  });

  restoreDraft();
  if (window.AutonoventAddressSearch) {
    window.AutonoventAddressSearch.attach(form, { endpoint: endpoint });
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) {
      return;
    }
    const selected = selectedQuote();
    const ready = flow.canSubmit({
      submitting: false,
      termsAccepted: Boolean(termsBox && termsBox.checked),
      quote: quote,
      selected: selected,
      ageMs: quoteAge(),
    });
    if (!termsBox || !termsBox.checked) {
      setStatus("Accept the Terms and Conditions before payment.");
      termsBox.focus();
      return;
    }
    if (!ready || !selected) {
      clearQuote();
      setStatus("Choose a current delivery option. A rate older than five minutes is checked again.");
      scheduleRates();
      return;
    }
    if (!submitLock.tryLock()) {
      return;
    }
    const button = form.querySelector("[data-place-order]");
    if (button) {
      button.disabled = true;
      button.textContent = "Opening payment…";
    }
    const data = new FormData(form);
    setStatus(checkoutMode === "sandbox" ? "Saving the order before the PayFast sandbox payment." : "Saving the simulated order.");
    csrf()
      .then((token) => post("/api/v1/checkout/orders", {
        idempotency_key: orderKey(),
        customer_name: recipientName(),
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
          releasePay();
          if (response.status === 409) {
            window.sessionStorage.removeItem(pendingKey);
          }
          if (response.status === 422) {
            clearQuote();
            scheduleRates();
          }
          return;
        }
        form.hidden = true;
        form.style.display = "none";
        rememberOrder(body);
        renderPayment(body);
      })
      .catch(() => {
        setStatus(checkoutMode === "sandbox" ? "The order could not be saved." : "The simulated order could not be placed.");
        releasePay();
      });
  });

  function showCart() {
    const lines = window.AutonoventCart.read();
    renderSummary();
    if (!lines.length) {
      setStatus("Your cart is empty. Add a listed product from the shop.");
      form.hidden = true;
      form.style.display = "none";
      return;
    }
    form.hidden = false;
    form.style.display = "";
    if (!quote) {
      setStatus("Enter a South African delivery address to see delivery rates.");
      scheduleRates();
    }
  }

  if (!endpoint) {
    setStatus("The checkout service is not configured.");
    return;
  }

  fetch(endpoint + "/api/v1/checkout/status", { headers: { Accept: "application/json" } })
    .then((response) => response.json())
    .then((body) => {
      checkoutMode = body && (body.checkout_mode === "sandbox" || body.checkout_mode === "simulation") ? body.checkout_mode : "unavailable";
      shippingQuotes = body && body.shipping_quotes === "shiplogic" ? "shiplogic" : "simulated";
      const banner = document.querySelector("[data-checkout-banner]");
      const paymentNote = document.querySelector("[data-payment-note]");
      if (checkoutMode === "unavailable") {
        setStatus("Checkout is not enabled.");
        return;
      }
      if (banner && checkoutMode === "simulation") {
        banner.textContent = shippingQuotes === "shiplogic"
          ? "Simulated test checkout. Delivery rates are ShipLogic sandbox prices and include VAT. Payments are not PayFast payments. No card details are collected."
          : "Simulated test checkout. Delivery quotes are not ShipLogic prices. Payments are not PayFast payments. No card details are collected.";
      }
      if (checkoutMode === "sandbox") {
        if (banner) {
          banner.textContent = "PayFast sandbox checkout. Delivery rates are ShipLogic sandbox prices and include VAT. Returning from PayFast does not mark the order paid.";
        }
        if (paymentNote) {
          paymentNote.textContent = "Pay Now continues to the PayFast sandbox. Returning from PayFast does not mark the order paid. Read the Privacy Notice before you continue.";
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
          showCart();
        });
    })
    .catch(() => setStatus("Checkout could not be loaded."));
})();
