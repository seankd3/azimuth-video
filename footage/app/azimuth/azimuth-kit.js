/* azimuth-kit.js: the behaviour the web components need beyond CSS (docs/components.md).
 *
 *   AzimuthKit.toast(panel, text, {action, onAction})  bottom-centre of panel; 4 s, 8 s with an
 *                                                      action; hovering holds it; one at a time
 *   AzimuthKit.lights(root)                            normal -> dim -> out -> normal (key L)
 *   AzimuthKit.sliders(root)                           keep each .az-slider's fill and value in step
 *   AzimuthKit.icon(name, size)                        <svg class="az-icon"><use href="#az-i-name">
 */
(function (global) {
  "use strict";
  var SPRITE = "";  // "" = the sprite is inlined in the page; else its URL, e.g. "vendor/azimuth/icons.svg"

  function icon(name, size) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "az-icon");
    svg.setAttribute("aria-hidden", "true");
    if (size) svg.setAttribute("data-size", String(size));
    var use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", SPRITE + "#az-i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function toast(panel, text, opts) {
    opts = opts || {};
    var host = panel.querySelector(":scope > .az-toasts");
    if (!host) {
      host = document.createElement("div");
      host.className = "az-toasts";
      host.setAttribute("role", "status");
      host.setAttribute("aria-live", "polite");
      if (getComputedStyle(panel).position === "static") panel.style.position = "relative";
      panel.appendChild(host);
    }
    host.textContent = "";
    var el = document.createElement("div");
    el.className = "az-toast az-float";
    var words = document.createElement("span");
    words.textContent = text;
    el.appendChild(words);
    if (opts.action) {
      var b = document.createElement("button");
      b.className = "az-btn";
      b.setAttribute("data-size", "small");
      b.textContent = opts.action;
      b.addEventListener("click", function () { done(); if (opts.onAction) opts.onAction(); });
      el.appendChild(b);
    }
    host.appendChild(el);
    var left = opts.action ? 8000 : 4000, started = Date.now(), timer = null;
    function done() { clearTimeout(timer); if (el.parentNode) el.parentNode.removeChild(el); }
    function run() { started = Date.now(); timer = setTimeout(done, left); }
    el.addEventListener("mouseenter", function () { clearTimeout(timer); left -= Date.now() - started; });
    el.addEventListener("mouseleave", function () { left = Math.max(left, 1500); run(); });
    run();
    return done;
  }

  var LIGHTS = ["", "dim", "out"];
  function lights(root) {
    root = root || document.documentElement;
    var now = root.getAttribute("data-lights") || "";
    var next = LIGHTS[(LIGHTS.indexOf(now) + 1) % LIGHTS.length];
    if (next) root.setAttribute("data-lights", next); else root.removeAttribute("data-lights");
    return next || "normal";
  }

  /* A slider fills from its rest value (data-rest, default its minimum) to its value. */
  function fill(input) {
    var min = +input.min || 0, max = input.max === "" ? 100 : +input.max, span = max - min || 1;
    var rest = input.hasAttribute("data-rest") ? +input.getAttribute("data-rest") : min;
    var a = (Math.min(rest, +input.value) - min) / span * 100, b = (Math.max(rest, +input.value) - min) / span * 100;
    input.style.setProperty("--az-fill-from", a + "%");
    input.style.setProperty("--az-fill-to", b + "%");
    var out = input.parentNode && input.parentNode.querySelector(".az-value");
    if (out && !out.hasAttribute("data-manual")) out.textContent = input.getAttribute("data-format")
      ? input.getAttribute("data-format").replace("{}", input.value) : input.value;
  }
  function sliders(root) {
    (root || document).querySelectorAll(".az-slider > input[type=range], input[type=range].az-range").forEach(function (input) {
      if (input.__az) { fill(input); return; }
      input.__az = true;
      input.addEventListener("input", function () { fill(input); });
      input.addEventListener("dblclick", function () {
        if (input.hasAttribute("data-rest")) { input.value = input.getAttribute("data-rest"); fill(input); input.dispatchEvent(new Event("input", { bubbles: true })); }
      });
      fill(input);
    });
  }

  global.AzimuthKit = {
    icon: icon, toast: toast, lights: lights, sliders: sliders,
    set sprite(url) { SPRITE = url || ""; }, get sprite() { return SPRITE; }
  };
})(typeof window !== "undefined" ? window : this);
