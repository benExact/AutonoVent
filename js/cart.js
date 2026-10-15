/* Browser cart for simulated checkout. Prices are not stored here. */

(function () {
  const storageKey = "autonovent-simulated-cart";

  function read() {
    try {
      const parsed = JSON.parse(window.sessionStorage.getItem(storageKey) || "[]");
      if (!Array.isArray(parsed)) {
        return [];
      }
      return parsed.filter((line) => line && typeof line.productId === "string" && Number.isInteger(line.quantity) && line.quantity > 0 && line.quantity <= 20);
    } catch (error) {
      return [];
    }
  }

  function write(lines) {
    window.sessionStorage.setItem(storageKey, JSON.stringify(lines));
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

  window.AutonoventCart = {
    read: read,
    write: write,
    add: add,
  };
})();
