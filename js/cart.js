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

  window.AutonoventCart = {
    read: read,
    write: write,
    add: add,
    setQuantity: setQuantity,
    remove: remove,
    count: count,
    updateCounts: updateCounts,
  };

  document.addEventListener("DOMContentLoaded", updateCounts);
})();
