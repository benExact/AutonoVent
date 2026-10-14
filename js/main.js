/* Shared site behaviour for the static marketing site. */

(function () {
  document.documentElement.classList.add("js");

  const yearNodes = document.querySelectorAll("[data-copyright-year]");
  const year = String(new Date().getFullYear());

  yearNodes.forEach((node) => {
    node.textContent = year;
  });

  const revealNodes = document.querySelectorAll("[data-reveal]");

  if (revealNodes.length && "IntersectionObserver" in window) {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");

    if (motionQuery.matches) {
      revealNodes.forEach((node) => {
        node.classList.add("is-visible");
      });
    } else {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (!entry.isIntersecting) {
              return;
            }

            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          });
        },
        { rootMargin: "0px 0px -8% 0px", threshold: 0.16 }
      );

      revealNodes.forEach((node) => {
        observer.observe(node);
      });
    }
  }

  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.querySelector("[data-site-nav]");

  if (!toggle || !nav) {
    return;
  }

  const label = toggle.querySelector("[data-nav-label]");
  const desktopQuery = window.matchMedia("(min-width: 64rem)");

  function setOpen(isOpen) {
    nav.classList.toggle("is-open", isOpen);
    toggle.setAttribute("aria-expanded", isOpen ? "true" : "false");

    if (label) {
      label.textContent = isOpen ? "Close menu" : "Open menu";
    }
  }

  function closeNav(restoreFocus) {
    const wasOpen = nav.classList.contains("is-open");
    setOpen(false);

    if (restoreFocus && wasOpen) {
      toggle.focus();
    }
  }

  toggle.addEventListener("click", () => {
    setOpen(!nav.classList.contains("is-open"));
  });

  nav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      closeNav(false);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeNav(true);
    }
  });

  document.addEventListener("click", (event) => {
    if (!nav.classList.contains("is-open")) {
      return;
    }

    const target = event.target;

    if (!(target instanceof Node)) {
      return;
    }

    if (nav.contains(target) || toggle.contains(target)) {
      return;
    }

    closeNav(false);
  });

  function handleDesktopChange(event) {
    if (event.matches) {
      closeNav(false);
    }
  }

  if (typeof desktopQuery.addEventListener === "function") {
    desktopQuery.addEventListener("change", handleDesktopChange);
  } else if (typeof desktopQuery.addListener === "function") {
    desktopQuery.addListener(handleDesktopChange);
  }
})();
