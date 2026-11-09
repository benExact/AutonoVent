/* Owner product history. The server filters and pages the audit records. */

(function () {
  const logout = document.querySelector("[data-auth-logout]");
  const authStatus = document.querySelector("[data-auth-status]");
  const form = document.querySelector("[data-history-form]");
  const host = document.querySelector("[data-history]");
  const status = document.querySelector("[data-history-status]");
  const base = window.AUTONOVENT_API_BASE_URL;
  const audit = window.OmniprodProductAudit;
  if (!logout || !authStatus || !form || !host || !status || typeof base !== "string" || !audit) {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  let page = 1;
  let loading = false;

  function setStatus(message) {
    status.textContent = message;
  }

  function api(path) {
    return fetch(endpoint + path, { credentials: "include", headers: { Accept: "application/json" } });
  }

  function csrfFromCookie() {
    const parts = document.cookie.split("; ");
    const match = parts.find((part) => part.startsWith("autonovent_csrf="));
    return match ? decodeURIComponent(match.slice("autonovent_csrf=".length)) : "";
  }

  function johannesburgToday() {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone: "Africa/Johannesburg",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date());
  }

  function shiftDate(iso, days) {
    const parts = iso.split("-").map(Number);
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }

  function defaultDates() {
    const end = johannesburgToday();
    return { start: shiftDate(end, -29), end: end };
  }

  function fillFieldOptions() {
    const select = form.querySelector("[data-history-field]");
    if (!select || !audit.fields) {
      return;
    }
    Object.keys(audit.fields).forEach(function (field) {
      const option = document.createElement("option");
      option.value = field;
      option.textContent = audit.fieldLabel(field);
      select.append(option);
    });
  }

  function applyDefaults() {
    const dates = defaultDates();
    form.start_date.value = dates.start;
    form.end_date.value = dates.end;
    form.product.value = "";
    form.changed_by.value = "";
    form.field.value = "";
    form.limit.value = "25";
  }

  function filters() {
    return {
      start_date: form.start_date.value,
      end_date: form.end_date.value,
      product: form.product.value.trim(),
      changed_by: form.changed_by.value.trim(),
      field: form.field.value,
      limit: form.limit.value || "25",
    };
  }

  function query(values, offset) {
    const params = new URLSearchParams();
    Object.keys(values).forEach(function (key) {
      if (values[key]) {
        params.set(key, values[key]);
      }
    });
    params.set("limit", values.limit || "25");
    params.set("offset", String(offset));
    return params.toString();
  }

  function detail(response) {
    return response.json().then(
      function (body) {
        return typeof body.detail === "string" ? body.detail : "The history could not be loaded.";
      },
      function () {
        return "The history could not be loaded.";
      }
    );
  }

  function load(nextPage) {
    if (loading) {
      return;
    }
    const values = filters();
    if (!values.start_date || !values.end_date) {
      setStatus("Choose both a start date and an end date.");
      return;
    }
    if (values.start_date > values.end_date) {
      setStatus("The start date cannot be later than the end date.");
      return;
    }
    page = nextPage;
    loading = true;
    setStatus("Loading history.");
    const offset = (page - 1) * Number(values.limit || 25);
    api("/api/v1/admin/audit?" + query(values, offset)).then(async function (response) {
      loading = false;
      if (response.status === 401) {
        window.location.assign("login.html");
        return;
      }
      if (!response.ok) {
        setStatus(await detail(response));
        return;
      }
      const payload = await response.json();
      audit.renderHistory(host, payload, {
        endpoint: endpoint,
        onPage: function (requested) {
          load(requested);
        },
      });
      setStatus(payload.total ? "" : "No changes in this date range.");
    }).catch(function () {
      loading = false;
      setStatus("The history could not be loaded.");
    });
  }

  logout.addEventListener("click", function () {
    fetch(endpoint + "/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "X-CSRF-Token": csrfFromCookie() },
    }).then(function (response) {
      if (response.status === 204) {
        window.location.assign("login.html");
        return;
      }
      setStatus("Sign out could not be completed.");
    }).catch(function () {
      setStatus("Sign out could not be completed.");
    });
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    load(1);
  });
  form.querySelector("[data-history-clear]").addEventListener("click", function () {
    applyDefaults();
    load(1);
  });
  form.limit.addEventListener("change", function () {
    load(1);
  });

  fillFieldOptions();
  applyDefaults();
  api("/api/v1/auth/me").then(function (response) {
    if (response.status === 401) {
      window.location.assign("login.html");
      return;
    }
    if (!response.ok) {
      setStatus("The sign-in service could not be reached.");
      return;
    }
    logout.hidden = false;
    load(1);
  }).catch(function () {
    setStatus("The sign-in service could not be reached.");
  });
})();
