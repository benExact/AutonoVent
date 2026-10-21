/* Browser cart. It stores product ids and quantities only. The server prices the order. */

(function () {
  const storageKey = "autonovent-cart";
  const legacyKey = "autonovent-simulated-cart";

  function normalise(parsed) {
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((line) => line && typeof line.productId === "string" && Number.isInteger(line.quantity) && line.quantity > 0 && line.quantity <= 20);
  }

  function read() {
    try {
      const current = window.localStorage.getItem(storageKey);
      if (current !== null) {
        return normalise(JSON.parse(current));
      }
      const legacy = window.sessionStorage.getItem(legacyKey);
      const lines = normalise(legacy ? JSON.parse(legacy) : []);
      if (lines.length) {
        write(lines);
      }
      return lines;
    } catch (error) {
      return [];
    }
  }

  function count() {
    return read().reduce((total, line) => total + line.quantity, 0);
  }

  function updateCounts() {
    const total = count();
    document.querySelectorAll("[data-cart-count]").forEach((node) => {
      node.textContent = String(total);
    });
  }

  function write(lines) {
    window.localStorage.setItem(storageKey, JSON.stringify(lines));
    window.sessionStorage.removeItem(legacyKey);
    updateCounts();
  }

  function add(productId) {
    const lines = read();
    const existing = lines.find((line) => line.productId === productId);
    if (existing) {
      existing.quantity = Math.min(existing.quantity + 1, 20);
    } else {
      lines.push({ productId: productId, quantity: 1 });
    }
    write(lines);
    return lines;
  }

  function setQuantity(productId, quantity) {
    const next = Number(quantity);
    if (!Number.isInteger(next) || next < 1) {
      return remove(productId);
    }
    const lines = read();
    const existing = lines.find((line) => line.productId === productId);
    if (!existing) {
      return lines;
    }
    existing.quantity = Math.min(next, 20);
    write(lines);
    return lines;
  }

  function remove(productId) {
    const lines = read().filter((line) => line.productId !== productId);
    write(lines);
    return lines;
  }

  function strokeIcon(paths) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    paths.forEach((definition) => {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", definition);
      path.setAttribute("fill", "none");
      path.setAttribute("stroke", "currentColor");
      path.setAttribute("stroke-width", "1.75");
      path.setAttribute("stroke-linecap", "round");
      path.setAttribute("stroke-linejoin", "round");
      svg.append(path);
    });
    return svg;
  }

  function iconButton(label, paths, className) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className || "icon-button";
    button.setAttribute("aria-label", label);
    button.title = label;
    button.append(strokeIcon(paths));
    return button;
  }

  function lineControls(productId, quantity, onChange) {
    const wrap = document.createElement("div");
    wrap.className = "qty-control";
    const stepper = document.createElement("div");
    stepper.className = "qty-stepper";
    stepper.setAttribute("role", "group");
    stepper.setAttribute("aria-label", "Quantity");
    const decrease = iconButton("Decrease quantity", ["M5 12h14"]);
    decrease.disabled = quantity <= 1;
    decrease.addEventListener("click", () => {
      setQuantity(productId, quantity - 1);
      onChange();
    });
    const value = document.createElement("span");
    value.className = "qty-value";
    value.textContent = String(quantity);
    const increase = iconButton("Increase quantity", ["M12 5v14", "M5 12h14"]);
    increase.disabled = quantity >= 20;
    increase.addEventListener("click", () => {
      setQuantity(productId, quantity + 1);
      onChange();
    });
    const removeItem = iconButton("Remove item", ["M4 7h16", "M10 11v6", "M14 11v6", "M9 7V5h6v2", "M7 7l1 12h8l1-12"], "icon-button qty-remove");
    removeItem.addEventListener("click", () => {
      remove(productId);
      onChange();
    });
    stepper.append(decrease, value, increase);
    wrap.append(stepper, removeItem);
    return wrap;
  }

  window.AutonoventCart = {
    read: read,
    write: write,
    add: add,
    setQuantity: setQuantity,
    remove: remove,
    lineControls: lineControls,
    count: count,
    updateCounts: updateCounts,
  };

  document.addEventListener("DOMContentLoaded", updateCounts);
})();
