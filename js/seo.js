/* Canonical URL and site metadata. The host is the origin serving the page. */

(function () {
  var configured = typeof window.AUTONOVENT_PUBLIC_ORIGIN === "string" ? window.AUTONOVENT_PUBLIC_ORIGIN.trim() : "";
  var origin = (configured || (window.location && window.location.origin) || "").replace(/\/$/, "");
  if (!origin || origin === "null" || origin === "file://") {
    return;
  }

  var path = window.location.pathname || "/";
  if (/\/index\.html$/.test(path)) {
    path = path.replace(/index\.html$/, "");
  }
  if (path.length > 1 && path.endsWith("/")) {
    path = path.slice(0, -1);
  }
  if (!path) {
    path = "/";
  }
  var canonicalUrl = origin + path;

  var canonical = document.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement("link");
    canonical.rel = "canonical";
    document.head.appendChild(canonical);
  }
  canonical.href = canonicalUrl;

  function ensureMeta(selector, attribute, name, content) {
    var node = document.head.querySelector(selector);
    if (!node) {
      node = document.createElement("meta");
      node.setAttribute(attribute, name);
      document.head.appendChild(node);
    }
    if (!node.getAttribute("content")) {
      node.setAttribute("content", content);
    }
    return node;
  }

  var description = document.querySelector('meta[name="description"]');
  var descriptionText = description ? description.getAttribute("content") || "" : "";
  ensureMeta('meta[property="og:site_name"]', "property", "og:site_name", "Autonovent");
  ensureMeta('meta[property="og:title"]', "property", "og:title", document.title);
  ensureMeta('meta[property="og:description"]', "property", "og:description", descriptionText);
  ensureMeta('meta[property="og:type"]', "property", "og:type", "website");
  ensureMeta('meta[property="og:locale"]', "property", "og:locale", "en_ZA");
  var ogUrl = ensureMeta('meta[property="og:url"]', "property", "og:url", canonicalUrl);
  if (!ogUrl.getAttribute("content")) {
    ogUrl.setAttribute("content", canonicalUrl);
  }
  var imagePath = document.documentElement.getAttribute("data-share-image") || "/assets/images/autonovent-logo.jpg";
  if (imagePath.charAt(0) !== "/") {
    imagePath = "/" + imagePath;
  }
  ensureMeta('meta[property="og:image"]', "property", "og:image", origin + imagePath);

  var home = document.getElementById("seo-home");
  if (!home) {
    return;
  }
  home.textContent = JSON.stringify({
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "Organization",
        name: "Autonovent",
        url: origin + "/",
        slogan: "Leave the dust behind.",
        logo: origin + "/assets/images/autonovent-logo.jpg"
      },
      {
        "@type": "WebSite",
        name: "Autonovent",
        url: origin + "/",
        inLanguage: "en-ZA"
      }
    ]
  });
})();
