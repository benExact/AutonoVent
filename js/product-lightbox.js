/* Larger view for the product photographs. Clicking the dark area or Close dismisses it. */

(function () {
  const images = document.querySelectorAll(".product-gallery img");
  const lightbox = document.querySelector("[data-photo-lightbox]");
  const view = document.querySelector("[data-photo-lightbox-image]");
  const closeButton = document.querySelector("[data-photo-close]");
  if (!images.length || !lightbox || !view || !closeButton) {
    return;
  }

  function open(image) {
    view.src = image.currentSrc || image.src;
    view.alt = image.alt || "Product photograph";
    lightbox.hidden = false;
    document.body.classList.add("photo-lightbox-open");
    closeButton.focus();
  }

  function close() {
    lightbox.hidden = true;
    view.removeAttribute("src");
    view.alt = "";
    document.body.classList.remove("photo-lightbox-open");
  }

  images.forEach((image) => {
    image.tabIndex = 0;
    image.setAttribute("role", "button");
    image.setAttribute("aria-label", image.alt ? "View larger. " + image.alt : "View larger photograph");
    image.addEventListener("click", () => open(image));
    image.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open(image);
      }
    });
  });

  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) {
      close();
    }
  });
  closeButton.addEventListener("click", close);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !lightbox.hidden) {
      close();
    }
  });
})();
