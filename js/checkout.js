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

  let csrfRequest = null;

  function csrfFromCookie() {
    const parts = document.cookie ? document.cookie.split("; ") : [];
    const match = parts.find((part) => part.startsWith("autonovent_csrf="));
    return match ? decodeURIComponent(match.slice("autonovent_csrf=".length)) : "";
  }

  function csrf() {
    const existing = csrfFromCookie();
    if (existing) {
      return Promise.resolve(existing);
    }
    if (!csrfRequest) {
      csrfRequest = fetch(endpoint + "/api/v1/auth/csrf", { credentials: "include", headers: { Accept: "application/json" } })
        .then((response) => response.json())
        .then((body) => body.csrf_token || csrfFromCookie())
        .finally(() => {
          csrfRequest = null;
        });
    }
    return csrfRequest;
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
      signal: AbortSignal.timeout(45000),
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
      empty.textContent = "No delivery options are available for this address.";
      quoteHost.append(empty, retryButton());
      renderSummary();
      return;
    }
    const offered = flow.customerQuotes(body.quotes);
    body = Object.assign({}, body, { quotes: offered });
    selectedCode = flow.selectionAfterQuote(selectedCode, offered);
    if (!offered.length) {
      const empty = document.createElement("p");
      empty.textContent = "No delivery options are available for this address.";
      quoteHost.append(empty, retryButton());
      renderSummary();
      return;
    }
    offered.forEach((option) => {
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
    if (!offered.some((option) => option.service_code === "ECO")) {
      setStatus("Economy is unavailable for this address. Choose one of the current delivery options.");
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
    setStatus(message);
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
    setStatus("Checking delivery options…");
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
        if (!body.quotes || !flow.customerQuotes(body.quotes).length) {
          setStatus("No delivery options are available for this address.");
          return;
        }
        if (!flow.customerQuotes(body.quotes).some((option) => option.service_code === "ECO")) {
          return;
        }
        setStatus("Economy is selected. You can choose another available delivery option.");
      })
      .catch(() => {
        if (requestId !== quoteRequest) {
          return;
        }
        showRateError("We couldn't load delivery options. Please try again.");
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
    title.textContent = "Order " + order.order_number;
    const amounts = document.createElement("p");
    amounts.textContent = "Subtotal " + money(order.subtotal_cents) + ". Delivery " + money(order.shipping_cents) + ". Total " + money(order.total_cents) + ".";
    const payment = document.createElement("p");
    payment.textContent = "Payment " + order.payment_status + ". Fulfilment " + order.fulfilment_status + ".";
    summary.append(title, amounts, payment);
    if (order.payment_reference) {
      const reference = document.createElement("p");
      reference.textContent = "Payment reference " + order.payment_reference + ".";
      summary.append(reference);
    }
    paymentHost.append(summary);
    if (order.payment_status !== "paid") {
      const pending = document.createElement("p");
      pending.textContent = "The order stays unpaid until payment is verified.";
      summary.append(pending);
    }
    if (order.payment_status === "paid") {
      setStatus("Payment has been verified.");
      const banner = document.querySelector("[data-checkout-banner]");
      if (banner) {
        banner.textContent = "Payment has been verified.";
      }
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
        setStatus("You have returned from payment. This order stays unpaid until the payment is verified.");
      } else if (returned === "cancel") {
        setStatus("The payment was cancelled. The order is not paid.");
      } else {
        setStatus("The order stays unpaid until payment is verified.");
      }
      const retry = document.createElement("button");
      retry.className = "button button--secondary";
      retry.type = "button";
      retry.textContent = "Continue to payment";
      retry.addEventListener("click", () => startPayfast(order.id));
      paymentHost.append(retry);
      return;
    }
    setStatus("Payment is temporarily unavailable. The order is not paid.");
  }

  function startPayfast(orderId) {
    return csrf()
      .then((token) => post("/api/v1/checkout/orders/" + orderId + "/payfast", {}, token))
      .then(async (response) => {
        const body = await response.json().catch(() => null);
        const attempt = flow.paymentAttempt({
          ok: response.ok,
          detail: response.ok ? "Payment is temporarily unavailable." : detailMessage(body),
          action: body && body.action,
          fields: body && body.fields,
        });
        if (!attempt.redirect) {
          setStatus(attempt.message);
          releasePay();
          return;
        }
        form.hidden = true;
        form.style.display = "none";
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
      .catch((error) => {
        const timedOut = error && (error.name === "TimeoutError" || error.name === "AbortError");
        setStatus(timedOut ? "The request timed out. The order is not paid." : "Payment could not be opened. The order is not paid.");
        releasePay();
      });
  }

  function restoreAfterFailure(error) {
    const timedOut = error && (error.name === "TimeoutError" || error.name === "AbortError");
    setStatus(timedOut ? "The request timed out. The order is not paid." : "The order could not be saved.");
    releasePay();
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
    if (!flow.paymentAvailable(checkoutMode)) {
      setStatus("Payment is temporarily unavailable.");
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
    setStatus("Saving the order before payment.");
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
          const detail = detailMessage(body);
          setStatus(detail === "Payment is temporarily unavailable." ? flow.paymentFailureMessage(detail) : detail);
          releasePay();
          if (response.status === 409) {
            window.sessionStorage.removeItem(pendingKey);
          }
          if (response.status === 422 && detail !== "Payment is temporarily unavailable.") {
            clearQuote();
            scheduleRates();
          }
          return;
        }
        rememberOrder(body);
        return startPayfast(body.id);
      })
      .catch((error) => restoreAfterFailure(error));
  });

  function refreshReturnedOrder(order) {
    let attempts = 0;
    let stopped = false;
    setStatus("Checking whether the payment has been verified.");
    function finish(fresh) {
      if (stopped) {
        return;
      }
      stopped = true;
      window.clearInterval(timer);
      rememberOrder(fresh);
      renderPayment(fresh);
    }
    function check() {
      if (stopped) {
        return;
      }
      attempts += 1;
      const decide = flow.paymentWatchDecision || function (attempt, status) {
        if (status === "paid" || status === "failed" || status === "cancelled" || attempt >= 90) {
          return "show";
        }
        return "wait";
      };
      fetch(endpoint + "/api/v1/checkout/orders/" + order.id, { headers: { Accept: "application/json" } })
        .then((response) => (response.ok ? response.json() : null))
        .then((fresh) => {
          if (!fresh || stopped) {
            return;
          }
          if (decide(attempts, fresh.payment_status) === "show") {
            finish(fresh);
          }
        })
        .catch(() => {
          if (decide(attempts, "pending") === "show") {
            stopped = true;
            window.clearInterval(timer);
          }
        });
    }
    const timer = window.setInterval(check, flow.paymentWatchIntervalMs || 2000);
    check();
  }

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
    setStatus("Checkout could not be loaded.");
    return;
  }

  fetch(endpoint + "/api/v1/checkout/status", { headers: { Accept: "application/json" } })
    .then((response) => response.json())
    .then((body) => {
      checkoutMode = body && (body.checkout_mode === "sandbox" || body.checkout_mode === "simulation") ? body.checkout_mode : "unavailable";
      shippingQuotes = body && body.shipping_quotes === "shiplogic" ? "shiplogic" : "simulated";
      const banner = document.querySelector("[data-checkout-banner]");
      if (checkoutMode === "unavailable") {
        setStatus("Checkout is not enabled.");
        return;
      }
      if (banner) {
        if (flow.paymentAvailable(checkoutMode)) {
          banner.hidden = true;
          banner.textContent = "";
        } else {
          banner.hidden = false;
          banner.textContent = "Payment is temporarily unavailable.";
        }
      }
      const payButton = form.querySelector("[data-place-order]");
      if (payButton && !flow.paymentAvailable(checkoutMode)) {
        payButton.disabled = true;
      }
      return fetch(endpoint + "/api/v1/products", { headers: { Accept: "application/json" } })
        .then((response) => response.json())
        .then((products) => {
          catalogue = products && Array.isArray(products.products) ? products.products : [];
          const pending = readPending();
          const returned = new URLSearchParams(window.location.search).get("payment");
          if (pending && pending.order && (returned === "return" || returned === "cancel" || pending.order.payment_status === "paid")) {
            form.hidden = true;
            form.style.display = "none";
            renderPayment(pending.order);
            if (returned === "return" && pending.order.payment_status !== "paid") {
              refreshReturnedOrder(pending.order);
            }
            return;
          }
          showCart();
          if (pending && pending.order) {
            setStatus("The saved order stays unpaid until payment is verified.");
          }
        });
    })
    .catch(() => setStatus("Checkout could not be loaded."));
})();
