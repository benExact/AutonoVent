/* Checkout decisions. Prices and payment status still come from the server. */

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.AutonoventCheckoutFlow = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const debounceMs = 450;
  const quoteLifetimeMs = 5 * 60 * 1000;
  const paymentWatchIntervalMs = 2000;
  const paymentWatchLimit = 90;
  const sandboxProcessUrl = "https://sandbox.payfast.co.za/eng/process";

  function clean(value) {
    return String(value || "").trim();
  }

  function customerName(first, last) {
    return [clean(first), clean(last)].filter(Boolean).join(" ");
  }

  function addressIsValid(address) {
    const line1 = clean(address && address.line1);
    const localArea = clean(address && address.local_area);
    const city = clean(address && address.city);
    const region = clean(address && address.region);
    const postal = clean(address && address.postal_code);
    const country = clean(address && address.country).toUpperCase();
    return line1.length > 0 && line1.length <= 200
      && localArea.length > 0 && localArea.length <= 120
      && city.length > 0 && city.length <= 120
      && region.length > 0 && region.length <= 120
      && /^[0-9]{4}$/.test(postal)
      && country === "ZA";
  }

  function addressKey(address, lines) {
    return JSON.stringify({
      line1: clean(address && address.line1),
      line2: clean(address && address.line2),
      local_area: clean(address && address.local_area),
      city: clean(address && address.city),
      region: clean(address && address.region),
      postal_code: clean(address && address.postal_code),
      country: clean(address && address.country).toUpperCase(),
      lines: lines || [],
    });
  }

  function quoteDecision(state) {
    if (!state || !state.valid) {
      return "wait";
    }
    if (state.inFlightKey && state.inFlightKey === state.key) {
      return "wait";
    }
    if (state.quotedKey && state.quotedKey === state.key && state.ageMs < quoteLifetimeMs) {
      return "wait";
    }
    return "request";
  }

  function createQuoteScheduler(delay) {
    let timer = null;
    let generation = 0;
    return {
      push(callback, clock) {
        generation += 1;
        const current = generation;
        if (timer !== null) {
          clock.clear(timer);
        }
        timer = clock.later(delay, function () {
          timer = null;
          if (current === generation) {
            callback();
          }
        });
      },
      cancel(clock) {
        generation += 1;
        if (timer !== null) {
          clock.clear(timer);
          timer = null;
        }
      },
    };
  }

  function matchingOption(quote, selected) {
    if (!quote || !quote.quotes || !selected) {
      return null;
    }
    return quote.quotes.find(function (option) {
      return option.service_code === selected.service_code && option.shipping_cents === selected.shipping_cents;
    }) || null;
  }

  function selectionIsCurrent(quote, selected, ageMs) {
    return Boolean(matchingOption(quote, selected)) && ageMs < quoteLifetimeMs;
  }

  function displayTotal(subtotalCents, option) {
    if (!option) {
      return { subtotalCents: subtotalCents, shippingCents: null, totalCents: null };
    }
    return {
      subtotalCents: subtotalCents,
      shippingCents: option.shipping_cents,
      totalCents: option.total_cents,
    };
  }

  function canSubmit(state) {
    return Boolean(state)
      && !state.submitting
      && state.termsAccepted === true
      && selectionIsCurrent(state.quote, state.selected, state.ageMs);
  }

  function createSubmitLock() {
    let locked = false;
    return {
      tryLock() {
        if (locked) {
          return false;
        }
        locked = true;
        return true;
      },
      release() {
        locked = false;
      },
    };
  }

  function formatProviderTime(value) {
    const parsed = new Date(value);
    if (!value || Number.isNaN(parsed.getTime())) {
      return "";
    }
    return new Intl.DateTimeFormat("en-ZA", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone: "Africa/Johannesburg",
    }).format(parsed);
  }

  function deliveryEstimate(option) {
    if (!option || !option.delivery_from || !option.delivery_to) {
      return "";
    }
    const start = formatProviderTime(option.delivery_from);
    const end = formatProviderTime(option.delivery_to);
    if (!start || !end) {
      return "";
    }
    return start + " to " + end;
  }

  function customerQuotes(quotes) {
    return (quotes || []).filter(function (option) {
      return option && (option.service_code === "ECO" || option.service_code === "LSE");
    });
  }

  function defaultServiceCode(quotes) {
    return customerQuotes(quotes).some(function (option) {
      return option.service_code === "ECO";
    }) ? "ECO" : "";
  }

  function selectionAfterQuote(previousCode, quotes) {
    const allowed = customerQuotes(quotes);
    const stillThere = previousCode && allowed.some(function (option) {
      return option.service_code === previousCode;
    });
    if (stillThere) {
      return previousCode;
    }
    return defaultServiceCode(allowed);
  }

  function paymentAvailable(mode) {
    return mode === "sandbox";
  }

  function payfastActionAllowed(action) {
    return action === sandboxProcessUrl;
  }

  function paymentFailureMessage(detail) {
    const message = typeof detail === "string" && detail.trim() ? detail.trim() : "Payment is temporarily unavailable.";
    if (/not paid\.?$/i.test(message)) {
      return message.endsWith(".") ? message : message + ".";
    }
    const base = message.endsWith(".") ? message.slice(0, -1) : message;
    return base + ". The order is not paid.";
  }

  function paymentWatchDecision(attempt, status) {
    if (status === "paid" || status === "failed" || status === "cancelled") {
      return "show";
    }
    if (attempt >= paymentWatchLimit) {
      return "show";
    }
    return "wait";
  }

  function paymentAttempt(result) {
    const fields = result && result.fields;
    const ready = Boolean(result && result.ok && payfastActionAllowed(result.action) && fields && Object.keys(fields).length);
    if (ready) {
      return { redirect: true, message: "" };
    }
    return { redirect: false, message: paymentFailureMessage(result && result.detail) };
  }

  return {
    debounceMs: debounceMs,
    quoteLifetimeMs: quoteLifetimeMs,
    paymentWatchIntervalMs: paymentWatchIntervalMs,
    paymentWatchLimit: paymentWatchLimit,
    paymentWatchDecision: paymentWatchDecision,
    sandboxProcessUrl: sandboxProcessUrl,
    customerName: customerName,
    addressIsValid: addressIsValid,
    addressKey: addressKey,
    quoteDecision: quoteDecision,
    createQuoteScheduler: createQuoteScheduler,
    matchingOption: matchingOption,
    selectionIsCurrent: selectionIsCurrent,
    displayTotal: displayTotal,
    canSubmit: canSubmit,
    createSubmitLock: createSubmitLock,
    deliveryEstimate: deliveryEstimate,
    customerQuotes: customerQuotes,
    defaultServiceCode: defaultServiceCode,
    selectionAfterQuote: selectionAfterQuote,
    paymentAvailable: paymentAvailable,
    payfastActionAllowed: payfastActionAllowed,
    paymentFailureMessage: paymentFailureMessage,
    paymentAttempt: paymentAttempt,
  };
});
