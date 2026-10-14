/* Enquiry delivery for the static marketing site.
   Set ENQUIRY_EMAIL to a confirmed Autonovent address before launch.
   Leave it empty until then. This file does not send email by itself. */

(function () {
  var ENQUIRY_EMAIL = "";

  var forms = document.querySelectorAll("[data-enquiry-form]");

  if (!forms.length) {
    return;
  }

  function trimmed(form, name) {
    var field = form.elements[name];
    return field ? field.value.trim() : "";
  }

  function showError(form, name, message) {
    var input = form.elements[name];
    var field = input && input.closest("[data-field]");
    var error = field && field.querySelector("[data-error]");

    if (!input || !error) {
      return;
    }

    if (message) {
      input.setAttribute("aria-invalid", "true");
      input.setAttribute("aria-describedby", error.id);
      error.hidden = false;
      error.textContent = message;
      return;
    }

    input.removeAttribute("aria-invalid");
    error.hidden = true;
    error.textContent = "";
  }

  function validEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  function validate(form) {
    var name = trimmed(form, "name");
    var email = trimmed(form, "email");
    var phone = trimmed(form, "phone");
    var message = trimmed(form, "message");
    var firstInvalid = null;

    function check(fieldName, message) {
      showError(form, fieldName, message);

      if (message && !firstInvalid) {
        firstInvalid = form.elements[fieldName];
      }
    }

    check("name", name.length < 2 ? "Enter your name." : "");
    check("email", validEmail(email) ? "" : "Enter a valid email address.");
    check(
      "phone",
      phone && phone.replace(/\D/g, "").length < 7
        ? "Enter a contact number with at least 7 digits, or leave this blank."
        : ""
    );
    check("message", message.length < 2 ? "Enter a message." : "");

    return firstInvalid;
  }

  function deliveryNote() {
    if (ENQUIRY_EMAIL) {
      return "Choosing Request a Quote opens your email application with this message. This website does not send it automatically.";
    }

    return "Enquiry delivery is not connected yet. This preview does not send messages. A contact address needs to be configured before the public launch.";
  }

  function setStatus(form, message) {
    var status = form.querySelector("[data-enquiry-status]");

    if (status) {
      status.textContent = message;
    }
  }

  forms.forEach(function (form) {
    var note = form.querySelector("[data-enquiry-note]");

    if (note) {
      note.textContent = deliveryNote();
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();

      var invalid = validate(form);

      if (invalid) {
        setStatus(form, "");
        invalid.focus();
        return;
      }

      if (!ENQUIRY_EMAIL) {
        setStatus(
          form,
          "Your message has not been sent. Enquiry delivery still needs to be configured before the public launch."
        );
        return;
      }

      var body = [
        "Name: " + trimmed(form, "name"),
        "Email: " + trimmed(form, "email"),
        "Contact number: " + (trimmed(form, "phone") || "Not provided"),
        "Quantity or intended use: " + (trimmed(form, "use") || "Not provided"),
        "",
        trimmed(form, "message")
      ].join("\n");

      var mailto =
        "mailto:" +
        ENQUIRY_EMAIL +
        "?subject=" +
        encodeURIComponent("Autonovent quote request") +
        "&body=" +
        encodeURIComponent(body);

      setStatus(
        form,
        "Your email application should open with this enquiry. Nothing has been sent automatically."
      );
      window.location.href = mailto;
    });
  });
})();
