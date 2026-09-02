/*
 * Preview bridge — runs INSIDE the sandboxed preview iframe.
 *
 * The preview iframe is sandboxed with "allow-scripts" but WITHOUT
 * "allow-same-origin", so the host page can no longer touch the iframe's DOM
 * directly (that is the point: LLM-authored code can't reach the host's
 * localStorage / window.parent). This script is injected into the previewed
 * HTML and is the ONLY channel between the preview and the host:
 *
 *   host  -> preview : { source: "s2c-host", type: "setSelectMode", enabled }
 *                      { source: "s2c-host", type: "clearSelection" }
 *   preview -> host  : { source: "s2c-preview", type: "ready" }
 *                      { source: "s2c-preview", type: "selected", element: {...} }
 *                      { source: "s2c-preview", type: "exitSelectMode" }
 *
 * The host validates event.source === iframe.contentWindow and
 * event.data.source === "s2c-preview" on every message.
 *
 * NOTE: the element-context logic here is a plain-JS mirror of
 * src/components/select-and-edit/utils.ts (describeElementContext) and
 * src/components/select-and-edit/overlays.ts. They are kept in sync by hand;
 * the TS versions remain the unit-tested source of truth.
 */
(function () {
  "use strict";
  if (window.__s2cPreviewBridge) return;
  window.__s2cPreviewBridge = true;

  var HOST = "s2c-host";
  var SELF = "s2c-preview";
  var MAX_ELEMENT_HTML_LENGTH = 12000;
  var MAX_PATH_DEPTH = 6;

  var selectMode = false;
  var hovered = null;
  var selected = null;

  function post(message) {
    try {
      // targetOrigin "*" is acceptable: a sandboxed (null-origin) parent cannot
      // be addressed by a specific origin, and the payload carries no secrets.
      window.parent.postMessage(Object.assign({ source: SELF }, message), "*");
    } catch (e) {
      /* parent gone */
    }
  }

  // --- overlays (mirror of overlays.ts) --------------------------------------
  var IDS = { hover: "__s2c-hover-overlay", selection: "__s2c-selection-overlay" };
  var CURSOR_ID = "__s2c-select-cursor";
  var STYLES = {
    hover: {
      zIndex: "2147483646",
      border: "1.5px solid rgba(124, 58, 237, 0.95)",
      background: "rgba(139, 92, 246, 0.09)",
      boxShadow: "0 0 0 3px rgba(139, 92, 246, 0.15)",
    },
    selection: {
      zIndex: "2147483645",
      border: "2.5px solid rgb(109, 40, 217)",
      background: "rgba(124, 58, 237, 0.16)",
      boxShadow:
        "0 0 0 2px rgba(255, 255, 255, 0.9), 0 2px 12px rgba(109, 40, 217, 0.45)",
    },
  };
  var LABEL_BG = { hover: "rgb(124, 58, 237)", selection: "rgb(91, 33, 182)" };
  var SELECTION_INSET = 3;

  function ensureOverlay(kind) {
    var el = document.getElementById(IDS[kind]);
    if (el) return el;
    el = document.createElement("div");
    el.id = IDS[kind];
    var base = {
      position: "fixed",
      top: "0",
      left: "0",
      width: "0",
      height: "0",
      pointerEvents: "none",
      borderRadius: "4px",
      transition: "none",
      animation: "none",
      display: "none",
    };
    Object.assign(el.style, base, STYLES[kind]);
    var label = document.createElement("div");
    Object.assign(label.style, {
      position: "absolute",
      left: "-2px",
      padding: "2px 7px",
      color: "#fff",
      font: "600 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace",
      borderRadius: "4px",
      whiteSpace: "nowrap",
      boxShadow: "0 1px 4px rgba(0, 0, 0, 0.25)",
      background: LABEL_BG[kind],
    });
    el.appendChild(label);
    document.documentElement.appendChild(el);
    return el;
  }

  function showOverlay(target, kind) {
    if (!target || target === document.documentElement) return;
    if (target.id === IDS.hover || target.id === IDS.selection) return;
    var overlay = ensureOverlay(kind);
    var rect = target.getBoundingClientRect();
    var inset = kind === "selection" ? SELECTION_INSET : 0;
    overlay.style.display = "block";
    overlay.style.top = rect.top - inset + "px";
    overlay.style.left = rect.left - inset + "px";
    overlay.style.width = rect.width + inset * 2 + "px";
    overlay.style.height = rect.height + inset * 2 + "px";
    var label = overlay.firstChild;
    if (label) {
      var tag = "<" + target.tagName.toLowerCase() + ">";
      label.textContent = kind === "selection" ? "✓ " + tag : tag;
      label.style.top = rect.top - inset > 26 ? "-24px" : "3px";
    }
  }

  function hideOverlay(kind) {
    var el = document.getElementById(IDS[kind]);
    if (el) el.style.display = "none";
  }

  function applyCursor() {
    if (document.getElementById(CURSOR_ID)) return;
    var style = document.createElement("style");
    style.id = CURSOR_ID;
    style.textContent = "* { cursor: crosshair !important; }";
    (document.head || document.documentElement).appendChild(style);
  }

  function removeCursor() {
    var el = document.getElementById(CURSOR_ID);
    if (el) el.remove();
  }

  function repositionOverlays() {
    if (hovered && hovered.isConnected) showOverlay(hovered, "hover");
    if (selected && selected.isConnected) showOverlay(selected, "selection");
  }

  // --- element context (mirror of utils.ts describeElementContext) ----------
  function describeNode(el) {
    var tag = el.tagName.toLowerCase();
    var classAttr = el.getAttribute("class") || "";
    var classes = classAttr.split(/\s+/).filter(Boolean).slice(0, 3);
    return tag + classes.map(function (c) { return "." + c; }).join("");
  }

  function describeElementContext(el) {
    var parts = [];
    var current = el;
    while (current && parts.length < MAX_PATH_DEPTH) {
      if (current.tagName.toLowerCase() === "html") break;
      parts.unshift(describeNode(current));
      current = current.parentElement;
    }
    var lines = ["Element location: " + parts.join(" > ")];
    var identical = Array.prototype.slice
      .call(el.ownerDocument.getElementsByTagName(el.tagName))
      .filter(function (other) { return other.outerHTML === el.outerHTML; });
    if (identical.length > 1) {
      var position = identical.indexOf(el) + 1;
      lines.push(
        identical.length +
          " elements on the page share this exact markup; the user selected number " +
          position +
          " of " +
          identical.length +
          " in document order. Edit only that one and leave the other copies exactly as they are. Because the markup repeats, do not locate the element by its own markup alone — anchor the edit with unique surrounding context (its parent element or a distinguishing ancestor class from the location path above), or scope a style change through that ancestor. Any search/replace whose search text matches more than one place will hit the wrong copy."
      );
    }
    return lines.join("\n");
  }

  function serialize(target) {
    var html = target.outerHTML || "";
    if (html.length > MAX_ELEMENT_HTML_LENGTH) {
      html =
        html.slice(0, MAX_ELEMENT_HTML_LENGTH) +
        "\n<!-- truncated; locate the element in the current code -->";
    }
    return {
      tagName: target.tagName.toLowerCase(),
      outerHTML: html,
      context: describeElementContext(target),
    };
  }

  // --- event handling ------------------------------------------------------
  function onClick(event) {
    if (!selectMode) return;
    event.preventDefault();
    event.stopPropagation();
    var target = event.target;
    if (!target || !target.getBoundingClientRect) return;
    selected = target;
    hovered = null;
    hideOverlay("hover");
    showOverlay(target, "selection");
    post({ type: "selected", element: serialize(target) });
  }

  function suppress(event) {
    if (selectMode) {
      event.preventDefault();
      event.stopPropagation();
    }
  }

  function onMouseOver(event) {
    if (!selectMode) return;
    var target = event.target;
    if (!target || !target.getBoundingClientRect) return;
    if (selected && (target === selected || selected.contains(target))) {
      hovered = null;
      hideOverlay("hover");
      return;
    }
    hovered = target;
    showOverlay(target, "hover");
  }

  function onMouseOut(event) {
    if (!selectMode || event.relatedTarget) return;
    hovered = null;
    hideOverlay("hover");
  }

  function onKeyDown(event) {
    if (selectMode && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      post({ type: "exitSelectMode" });
    }
  }

  window.addEventListener("click", onClick, true);
  ["pointerdown", "mousedown", "mouseup", "submit"].forEach(function (type) {
    window.addEventListener(type, suppress, true);
  });
  window.addEventListener("mouseover", onMouseOver, true);
  window.addEventListener("mouseout", onMouseOut, true);
  window.addEventListener("scroll", repositionOverlays, true);
  window.addEventListener("resize", repositionOverlays);
  window.addEventListener("keydown", onKeyDown, true);
  // Block link navigation for in-page anchors while selecting.
  document.addEventListener("click", function (event) {
    if (!selectMode) return;
    var anchor = event.target && event.target.closest && event.target.closest("a");
    var href = anchor && anchor.getAttribute("href");
    if (href && href.charAt(0) === "#") event.preventDefault();
  });

  window.addEventListener("message", function (event) {
    var data = event.data;
    if (!data || data.source !== HOST) return;
    if (data.type === "setSelectMode") {
      selectMode = !!data.enabled;
      if (selectMode) {
        applyCursor();
      } else {
        selected = null;
        hovered = null;
        removeCursor();
        hideOverlay("hover");
        hideOverlay("selection");
      }
    } else if (data.type === "clearSelection") {
      selected = null;
      hideOverlay("selection");
    }
  });

  post({ type: "ready" });
})();
