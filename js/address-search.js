/* Address suggestions. A selected result only fills components the provider returned. */

(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.AutonoventAddressSearch = api;
})(typeof window !== "undefined" ? window : globalThis, function () {
  const fields = ["line1", "line2", "local_area", "city", "region", "postal_code", "country"];

  function createSearchState() {
    return { generation: 0, selectedId: "", selectedLine1: "" };
  }

  function nextGeneration(state) {
    state.generation += 1;
    return state.generation;
  }

  function isCurrentGeneration(state, generation) {
    return generation === state.generation;
  }

  function applyAddress(current, selection) {
    const next = {};
    const missing = [];
    fields.forEach((key) => {
      next[key] = current[key] || "";
      const value = selection && typeof selection[key] === "string" ? selection[key].trim() : "";
      if (value) {
        next[key] = value;
      } else if (key !== "line2" && !next[key]) {
        missing.push(key);
      }
    });
    return { fields: next, missing: missing };
  }

  function rememberSelection(state, placeId, line1) {
    state.selectedId = placeId;
    state.selectedLine1 = line1;
  }

  function selectionStillMatches(state, line1) {
    return Boolean(state.selectedId) && state.selectedLine1 === line1;
  }

  function attach(form, options) {
    const input = form.querySelector("#address-search");
    const list = form.querySelector("#address-suggestions");
    const status = form.querySelector("[data-address-status]");
    const endpoint = options.endpoint || "";
    const fetchImpl = options.fetch || window.fetch;
    const state = createSearchState();
    let timer = 0;
    let active = -1;
    let suggestions = [];

    if (!input || !list || !status) {
      return;
    }

    function setStatus(message) {
      status.textContent = message;
    }

    function closeList() {
      list.hidden = true;
      list.replaceChildren();
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      active = -1;
      suggestions = [];
    }

    function readFields() {
      const data = new FormData(form);
      return {
        line1: String(data.get("line1") || ""),
        line2: String(data.get("line2") || ""),
        local_area: String(data.get("local_area") || ""),
        city: String(data.get("city") || ""),
        region: String(data.get("region") || ""),
        postal_code: String(data.get("postal_code") || ""),
        country: String(data.get("country") || ""),
      };
    }

    function writeFields(values) {
      fields.forEach((key) => {
        const control = form.elements[key];
        if (control && Object.prototype.hasOwnProperty.call(values, key)) {
          control.value = values[key];
        }
      });
    }

    function markEdited() {
      const line1 = String(new FormData(form).get("line1") || "");
      if (state.selectedId && !selectionStillMatches(state, line1)) {
        state.selectedId = "";
        state.selectedLine1 = "";
        setStatus("The street address changed after the suggestion. Check the address fields before continuing.");
      }
    }

    function render() {
      list.replaceChildren();
      suggestions.forEach((item, index) => {
        const option = document.createElement("li");
        option.id = "address-option-" + index;
        option.setAttribute("role", "option");
        const button = document.createElement("button");
        button.type = "button";
        button.textContent = item.label;
        button.setAttribute("aria-selected", index === active ? "true" : "false");
        button.addEventListener("click", () => choose(index));
        option.append(button);
        list.append(option);
      });
      list.hidden = suggestions.length === 0;
      input.setAttribute("aria-expanded", suggestions.length ? "true" : "false");
      if (active >= 0 && suggestions[active]) {
        input.setAttribute("aria-activedescendant", "address-option-" + active);
      } else {
        input.removeAttribute("aria-activedescendant");
      }
    }

    function choose(index) {
      const item = suggestions[index];
      if (!item) {
        return;
      }
      const generation = nextGeneration(state);
      setStatus("Loading the selected address.");
      input.setAttribute("aria-busy", "true");
      fetchImpl(endpoint + "/api/v1/addresses/selection?id=" + encodeURIComponent(item.id), {
        headers: { Accept: "application/json" },
      })
        .then((response) => response.json().then((body) => ({ ok: response.ok, body: body })))
        .then((result) => {
          if (!isCurrentGeneration(state, generation)) {
            return;
          }
          input.removeAttribute("aria-busy");
          if (!result.ok || !result.body) {
            setStatus((result.body && result.body.detail) || "That address could not be loaded. Enter it manually.");
            return;
          }
          const applied = applyAddress(readFields(), result.body);
          writeFields(applied.fields);
          rememberSelection(state, item.id, applied.fields.line1);
          input.value = item.label;
          input.dataset.selectedLabel = item.label;
          closeList();
          if (applied.missing.length || !result.body.line2) {
            setStatus("The suggestion did not include every detail. Add a unit or complex if you need one, and check the fields before continuing.");
          } else {
            setStatus("Address suggestion applied. You can still correct any field.");
          }
        })
        .catch(() => {
          if (!isCurrentGeneration(state, generation)) {
            return;
          }
          input.removeAttribute("aria-busy");
          setStatus("That address could not be loaded. Enter it manually.");
        });
    }

    function search() {
      const query = input.value.trim();
      const generation = nextGeneration(state);
      if (state.selectedId && query !== input.dataset.selectedLabel) {
        state.selectedId = "";
        state.selectedLine1 = "";
      }
      if (query.length < 3) {
        closeList();
        setStatus(query ? "Keep typing to search, or enter the address below." : "Start typing a South African address, or enter the fields below yourself.");
        return;
      }
      setStatus("Searching for addresses.");
      input.setAttribute("aria-busy", "true");
      fetchImpl(endpoint + "/api/v1/addresses/suggestions?q=" + encodeURIComponent(query), {
        headers: { Accept: "application/json" },
      })
        .then((response) => response.json().then((body) => ({ ok: response.ok, body: body || {} })))
        .then((result) => {
          if (!isCurrentGeneration(state, generation)) {
            return;
          }
          input.removeAttribute("aria-busy");
          if (!result.ok) {
            closeList();
            setStatus((result.body && result.body.detail) || "Address search is unavailable. Enter the address manually.");
            return;
          }
          if (result.body.enabled === false) {
            closeList();
            setStatus(result.body.detail || "Address search is not configured. Enter the address manually.");
            return;
          }
          suggestions = Array.isArray(result.body.suggestions) ? result.body.suggestions : [];
          active = suggestions.length ? 0 : -1;
          render();
          setStatus(suggestions.length ? "Select an address, or keep typing." : "No matching addresses. Enter the address manually.");
        })
        .catch(() => {
          if (!isCurrentGeneration(state, generation)) {
            return;
          }
          input.removeAttribute("aria-busy");
          closeList();
          setStatus("Address search is unavailable. Enter the address manually.");
        });
    }

    input.addEventListener("input", () => {
      if (state.selectedId && input.value !== (input.dataset.selectedLabel || "")) {
        state.selectedId = "";
        state.selectedLine1 = "";
        setStatus("The address search changed after the suggestion. Check the fields below or choose a suggestion again.");
      }
      window.clearTimeout(timer);
      timer = window.setTimeout(search, options.delay || 300);
    });
    input.addEventListener("keydown", (event) => {
      if (list.hidden) {
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        active = Math.min(suggestions.length - 1, active + 1);
        render();
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        active = Math.max(0, active - 1);
        render();
      } else if (event.key === "Enter" && active >= 0) {
        event.preventDefault();
        choose(active);
      } else if (event.key === "Escape") {
        closeList();
      }
    });
    document.addEventListener("click", (event) => {
      if (!input.parentElement.contains(event.target)) {
        closeList();
      }
    });
    const line1 = form.elements.line1;
    if (line1) {
      line1.addEventListener("input", markEdited);
    }
  }

  return {
    createSearchState: createSearchState,
    nextGeneration: nextGeneration,
    isCurrentGeneration: isCurrentGeneration,
    applyAddress: applyAddress,
    rememberSelection: rememberSelection,
    selectionStillMatches: selectionStillMatches,
    attach: attach,
  };
});
