/* Homepage promotional banners. Disabled slides stay on the server. */

(function () {
  const root = document.querySelector("[data-store-hero]");
  const frame = document.querySelector("[data-hero-visual]");
  const fallback = document.querySelector("[data-hero-fallback]");
  const nav = document.querySelector("[data-hero-nav]");
  const dots = document.querySelector("[data-hero-dots]");
  const base = window.AUTONOVENT_API_BASE_URL;
  if (!root || !frame || !fallback || !nav || !dots || typeof base !== "string") {
    return;
  }

  const endpoint = base.replace(/\/$/, "");
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let slides = [];
  let index = 0;
  let timer = 0;
  let paused = false;

  function imageSource(slide) {
    if (slide && typeof slide.image_url === "string" && slide.image_url.indexOf("/media/carousel/") === 0) {
      return endpoint + slide.image_url;
    }
    return "";
  }

  function stop() {
    window.clearInterval(timer);
    timer = 0;
  }

  function start() {
    stop();
    if (reducedMotion || paused || slides.length < 2) {
      return;
    }
    timer = window.setInterval(() => show(index + 1), 5000);
  }

  function show(next) {
    if (!slides.length) {
      return;
    }
    index = (next + slides.length) % slides.length;
    const nodes = frame.querySelectorAll(".banner-slide");
    nodes.forEach((node, position) => {
      const active = position === index;
      node.classList.toggle("is-active", active);
      node.setAttribute("aria-hidden", active ? "false" : "true");
    });
    dots.querySelectorAll(".hero-dot").forEach((dot, position) => {
      if (position === index) {
        dot.setAttribute("aria-current", "true");
      } else {
        dot.removeAttribute("aria-current");
      }
    });
  }

  function render(items) {
    slides = items.filter((item) => imageSource(item));
    frame.querySelectorAll(".banner-slide").forEach((node) => node.remove());
    dots.replaceChildren();
    if (!slides.length) {
      fallback.hidden = false;
      nav.hidden = true;
      stop();
      return;
    }
    fallback.hidden = true;
    slides.forEach((slide, position) => {
      const node = document.createElement("div");
      node.className = "banner-slide" + (position === 0 ? " is-active" : "");
      node.setAttribute("aria-hidden", position === 0 ? "false" : "true");
      const image = document.createElement("img");
      image.src = imageSource(slide);
      image.width = 1920;
      image.height = 600;
      image.alt = slide.title || slide.message ? "" : "Promotional banner";
      node.appendChild(image);
      if (slide.title || slide.message) {
        const copy = document.createElement("div");
        copy.className = "banner-slide__copy";
        if (slide.title) {
          const title = document.createElement("p");
          title.className = "banner-slide__title";
          title.textContent = slide.title;
          copy.appendChild(title);
        }
        if (slide.message) {
          const message = document.createElement("p");
          message.className = "banner-slide__message";
          message.textContent = slide.message;
          copy.appendChild(message);
        }
        node.appendChild(copy);
      }
      frame.appendChild(node);
      const dot = document.createElement("button");
      dot.className = "hero-dot";
      dot.type = "button";
      dot.setAttribute("aria-label", "Show promotion " + (position + 1));
      if (position === 0) {
        dot.setAttribute("aria-current", "true");
      }
      dot.addEventListener("click", () => {
        show(position);
        start();
      });
      dots.appendChild(dot);
    });
    nav.hidden = slides.length < 2;
    index = 0;
    start();
  }

  root.querySelector("[data-hero-prev]").addEventListener("click", () => {
    show(index - 1);
    start();
  });
  root.querySelector("[data-hero-next]").addEventListener("click", () => {
    show(index + 1);
    start();
  });
  root.addEventListener("keydown", (event) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      show(index - 1);
      start();
    }
    if (event.key === "ArrowRight") {
      event.preventDefault();
      show(index + 1);
      start();
    }
  });
  root.addEventListener("pointerenter", () => {
    paused = true;
    stop();
  });
  root.addEventListener("pointerleave", () => {
    paused = root.contains(document.activeElement);
    start();
  });
  root.addEventListener("focusin", () => {
    paused = true;
    stop();
  });
  root.addEventListener("focusout", () => {
    window.setTimeout(() => {
      paused = root.contains(document.activeElement);
      start();
    }, 0);
  });

  fetch(endpoint + "/api/v1/carousel", { headers: { Accept: "application/json" } })
    .then((response) => (response.ok ? response.json() : Promise.reject()))
    .then((body) => render(Array.isArray(body.slides) ? body.slides : []))
    .catch(() => render([]));
})();
