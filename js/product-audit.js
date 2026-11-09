/* Product change history. Stored audit rows are only displayed here. */

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.OmniprodProductAudit = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const labels = {
    name: "Product Name",
    slug: "Slug",
    description: "Description",
    short_description: "Short Description",
    sku: "SKU",
    unit_price_cents: "Product Price",
    currency: "Currency",
    active: "Product Status",
    in_stock: "Stock Availability",
    archived_at: "Archived",
    image_filename: "Product Image",
    specification_enabled: "Specification Sheet Enabled",
    specification_stored_name: "Specification Sheet File",
    specification_original_name: "Specification Sheet Name",
  };
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const imageName = /^[0-9a-f]{32}\.(jpg|png|webp)$/;
  const galleryName = /^[a-z0-9]+(?:-[a-z0-9]+)*\/[0-9a-f]{16}(?:-thumb)?\.webp$/;
  const previewLimit = 140;

  function fieldLabel(field) {
    return labels[field] || "Field";
  }

  function isEmpty(value) {
    return value === null || value === undefined || value === "";
  }

  function formatWhen(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return { date: "Not recorded", time: "" };
    }
    const day = String(date.getDate()).padStart(2, "0");
    const hours = String(date.getHours()).padStart(2, "0");
    const minutes = String(date.getMinutes()).padStart(2, "0");
    return { date: day + " " + months[date.getMonth()] + " " + date.getFullYear(), time: hours + ":" + minutes };
  }

  function formatPrice(cents) {
    if (!Number.isInteger(cents)) {
      return "—";
    }
    const sign = cents < 0 ? "-" : "";
    const amount = Math.abs(cents);
    const whole = String(Math.floor(amount / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return sign + "R" + whole + "." + String(amount % 100).padStart(2, "0");
  }

  function formatBoolean(field, value) {
    if (field === "active") {
      return value ? "Active" : "Inactive";
    }
    if (field === "in_stock") {
      return value ? "In stock" : "Out of stock";
    }
    return value ? "Enabled" : "Disabled";
  }

  function readableFile(value) {
    const text = String(value || "");
    if (!text || text.indexOf("\\") >= 0 || text.indexOf("..") >= 0 || /^[a-zA-Z]:/.test(text)) {
      return "";
    }
    const slash = text.lastIndexOf("/");
    return slash >= 0 ? text.slice(slash + 1) : text;
  }

  function imageUrl(endpoint, value) {
    if (typeof value !== "string" || !(imageName.test(value) || galleryName.test(value))) {
      return "";
    }
    return String(endpoint || "").replace(/\/$/, "") + "/media/products/" + value;
  }

  function formatValue(field, value) {
    if (isEmpty(value)) {
      return "—";
    }
    if (field === "unit_price_cents") {
      return formatPrice(value);
    }
    if (typeof value === "boolean") {
      return formatBoolean(field, value);
    }
    if (field === "image_filename" || field === "specification_stored_name" || field === "specification_original_name") {
      return readableFile(value) || "—";
    }
    return String(value);
  }

  function newestFirst(events) {
    return events.slice().reverse();
  }

  function render(host, events, options) {
    const settings = options || {};
    const pageSize = settings.pageSize || 8;
    host.replaceChildren();
    const source = Array.isArray(events) ? events : [];
    if (!source.length) {
      host.textContent = "No changes have been recorded.";
      return;
    }
    const ordered = newestFirst(source);
    const pages = Math.max(1, Math.ceil(ordered.length / pageSize));
    const page = Math.min(Math.max(0, settings.page || 0), pages - 1);
    const visible = ordered.slice(page * pageSize, page * pageSize + pageSize);
    const wrap = document.createElement("div");
    wrap.className = "audit-table-wrap";
    const table = document.createElement("table");
    table.className = "audit-table";
    const caption = document.createElement("caption");
    caption.className = "visually-hidden";
    caption.textContent = "Change history";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["Date & Time", "Changed By", "Field Changed", "Previous Value", "New Value"].forEach(function (text) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = text;
      headRow.append(cell);
    });
    head.append(headRow);
    table.append(caption, head);
    visible.forEach(function (event, index) {
      table.append(eventBody(event, index, settings.endpoint));
    });
    wrap.append(table);
    host.append(wrap);
    if (pages > 1) {
      host.append(pager(page, pages, settings.onPage));
    }
  }

  function eventBody(event, index, endpoint) {
    const body = document.createElement("tbody");
    body.className = "audit-group" + (index % 2 ? " audit-group--shade" : "");
    const when = formatWhen(event.created_at);
    const actor = typeof event.actor === "string" && event.actor.trim() ? event.actor.trim() : "Not recorded";
    const changes = Array.isArray(event.changes) && event.changes.length ? event.changes : [{ field: "", previous: null, new: null }];
    changes.forEach(function (change, changeIndex) {
      const row = document.createElement("tr");
      if (changeIndex > 0) {
        row.className = "audit-continued";
      }
      row.append(
        whenCell(when, changeIndex === 0),
        textCell("Changed By", changeIndex === 0 ? actor : "", "audit-actor"),
        textCell("Field Changed", fieldLabel(change.field), "audit-field"),
        valueCell("Previous Value", change.field, change.previous, "previous", endpoint),
        valueCell("New Value", change.field, change.new, "new", endpoint)
      );
      body.append(row);
    });
    return body;
  }

  function whenCell(when, first) {
    const cell = document.createElement("td");
    cell.className = "audit-when";
    cell.dataset.label = "Date & Time";
    if (!first) {
      return cell;
    }
    const date = document.createElement("span");
    date.className = "audit-when__date";
    date.textContent = when.date;
    cell.append(date);
    if (when.time) {
      const time = document.createElement("span");
      time.className = "audit-when__time";
      time.textContent = when.time;
      cell.append(time);
    }
    return cell;
  }

  function textCell(label, text, className) {
    const cell = document.createElement("td");
    cell.className = className;
    cell.dataset.label = label;
    cell.textContent = text;
    return cell;
  }

  function valueCell(label, field, value, role, endpoint) {
    const cell = document.createElement("td");
    cell.className = "audit-value" + (role === "new" ? " audit-value--new" : "");
    cell.dataset.label = label;
    if (field === "image_filename" && !isEmpty(value)) {
      cell.append(imageValue(value, role, endpoint));
      return cell;
    }
    const text = formatValue(field, value);
    if (text === "—") {
      cell.textContent = "—";
      return cell;
    }
    if (text.length > previewLimit || text.indexOf("\n") >= 0) {
      cell.append(longValue(text));
      return cell;
    }
    cell.textContent = text;
    return cell;
  }

  function longValue(text) {
    const block = document.createElement("div");
    block.className = "audit-text";
    const preview = document.createElement("p");
    preview.className = "audit-text__preview";
    const needsCut = text.length > previewLimit;
    preview.textContent = needsCut ? text.slice(0, previewLimit).trimEnd() + "…" : text;
    const full = document.createElement("p");
    full.className = "audit-text__full";
    full.hidden = true;
    full.textContent = text;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "audit-text__toggle";
    button.textContent = "View more";
    button.setAttribute("aria-expanded", "false");
    button.addEventListener("click", function () {
      const open = full.hidden;
      full.hidden = !open;
      preview.hidden = open;
      button.textContent = open ? "View less" : "View more";
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
    block.append(preview, full, button);
    return block;
  }

  function imageValue(value, role, endpoint) {
    const block = document.createElement("div");
    block.className = "audit-image";
    const src = imageUrl(endpoint, value);
    const name = readableFile(value);
    if (!src) {
      block.textContent = role === "previous" ? "Previous image unavailable" : "Image unavailable";
      return block;
    }
    const image = document.createElement("img");
    image.className = "audit-thumb";
    image.alt = "";
    image.src = src;
    const caption = document.createElement("span");
    caption.className = "audit-image__name";
    caption.textContent = name;
    image.addEventListener("error", function () {
      image.remove();
      caption.remove();
      block.textContent = role === "previous" ? "Previous image unavailable" : "Image unavailable";
    });
    block.append(image, caption);
    return block;
  }

  function pager(page, pages, onPage) {
    const bar = document.createElement("div");
    bar.className = "audit-pager";
    const previous = document.createElement("button");
    previous.type = "button";
    previous.className = "button button--secondary";
    previous.textContent = "Previous";
    previous.disabled = page === 0;
    previous.addEventListener("click", function () {
      if (typeof onPage === "function") {
        onPage(page - 1);
      }
    });
    const status = document.createElement("p");
    status.textContent = "Page " + (page + 1) + " of " + pages;
    const next = document.createElement("button");
    next.type = "button";
    next.className = "button button--secondary";
    next.textContent = "Next";
    next.disabled = page >= pages - 1;
    next.addEventListener("click", function () {
      if (typeof onPage === "function") {
        onPage(page + 1);
      }
    });
    bar.append(previous, status, next);
    return bar;
  }

  return {
    fieldLabel: fieldLabel,
    formatWhen: formatWhen,
    formatValue: formatValue,
    imageUrl: imageUrl,
    newestFirst: newestFirst,
    render: render,
  };
});
