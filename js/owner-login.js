/* Owner sign-in. It never stores the password or displays order data. */

(function () {
  const form = document.querySelector("[data-auth-form]");
  const status = document.querySelector("[data-auth-status]");
  const logout = document.querySelector("[data-auth-logout]");
  const base = window.AUTONOVENT_API_BASE_URL;

  if (!form || !status || !logout || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");

  function setStatus(message) {
    status.textContent = message;
  }

  function csrfFromCookie() {
    const parts = document.cookie.split("; ");
    const match = parts.find((part) => part.startsWith("autonovent_csrf="));
    return match ? decodeURIComponent(match.slice("autonovent_csrf=".length)) : "";
  }

  function prepareCsrf() {
    return fetch(endpoint + "/api/v1/auth/csrf", { credentials: "include" })
      .then((response) => {
        if (!response.ok) {
          throw new Error("csrf");
        }
        return response.json();
      })
      .then((body) => body.csrf_token || csrfFromCookie());
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const email = form.email.value;
    const password = form.password.value;
    setStatus("Signing in.");
    prepareCsrf()
      .then((token) =>
        fetch(endpoint + "/api/v1/auth/login", {
          method: "POST",
          credentials: "include",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
          },
          body: JSON.stringify({ email: email, password: password }),
        })
      )
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (response.status === 200 && body.role === "owner") {
          window.location.assign("orders.html");
          return;
        }
        setStatus(typeof body.detail === "string" ? body.detail : "The sign-in service could not be reached.");
      })
      .catch(() => {
        setStatus("The sign-in service could not be reached.");
      });
  });

  fetch(endpoint + "/api/v1/auth/me", { credentials: "include" })
    .then((response) => {
      if (response.status === 200) {
        window.location.assign("orders.html");
      }
    })
    .catch(() => {});

  logout.addEventListener("click", () => {
    const token = csrfFromCookie();
    fetch(endpoint + "/api/v1/auth/logout", {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": token },
    })
      .then((response) => {
        if (response.status !== 204) {
          throw new Error("logout");
        }
        form.hidden = false;
        logout.hidden = true;
        setStatus("You are signed out.");
      })
      .catch(() => {
        setStatus("Sign out could not be completed.");
      });
  });
})();
