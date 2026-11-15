/* azimuth-kit.js: the behaviour the web components need beyond CSS (docs/components.md).
 *
 *   AzimuthKit.toast(panel, text, {action, onAction})  bottom-centre of panel; 4 s, 8 s with an
 *                                                      action; hovering holds it; one at a time
 *   AzimuthKit.lights(root)                            normal -> dim -> out -> normal (key L)
 *   AzimuthKit.sliders(root)                           keep each .az-slider's fill and value in step
 *   AzimuthKit.icon(name, size)                        <svg class="az-icon"><use href="#az-i-name">
 *   AzimuthKit.themes(select, {key, follow, themes})   the one theme picker: System / Azimuth Dark /
 *                                                      Azimuth Light, remembered; System follows a live
 *                                                      theme file when the app serves one (follow: url);
 *                                                      ?theme=<id> picks one for a single visit
 *
 * To avoid a flash, call AzimuthKit.themes.restore(key) from a script in <head> (needs only this file).
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

  /* ── the theme picker ── */
  var MODES = { "azimuth-dark": "dark", "azimuth-light": "light" };
  function read(key) { try { return localStorage.getItem(key) || "system"; } catch (e) { return "system"; } }
  function write(key, v) { try { localStorage.setItem(key, v); } catch (e) {} }
  function setBuiltIn(root, id) {
    if (id === "system") { root.removeAttribute("data-theme"); root.removeAttribute("data-mode"); return; }
    root.setAttribute("data-theme", id);
    root.setAttribute("data-mode", MODES[id] || "dark");
  }
  function themes(select, opts) {
    opts = opts || {};
    var key = opts.key || "az-theme", root = opts.root || document.documentElement, stop = null;
    var list = opts.themes || [["system", "System"], ["azimuth-dark", "Azimuth Dark"], ["azimuth-light", "Azimuth Light"]];
    if (!select.options.length) list.forEach(function (t) { var o = document.createElement("option"); o.value = t[0]; o.textContent = t[1]; select.appendChild(o); });
    function use(v) {
      if (stop) { stop(); stop = null; }
      if (global.AzimuthTheme) global.AzimuthTheme.clear(root);
      setBuiltIn(root, v);
      if (v === "system" && opts.follow && global.AzimuthTheme) stop = global.AzimuthTheme.follow(opts.follow);
      select.value = v;
      if (opts.onChange) opts.onChange(v);
    }
    select.addEventListener("change", function () { write(key, select.value); use(select.value); });
    // ?theme=<id> picks a theme for this visit only (opts.param, default "theme"); it isn't remembered.
    var once = null;
    try { once = new URLSearchParams(location.search).get(opts.param || "theme"); } catch (e) {}
    var valid = list.some(function (t) { return t[0] === once; });
    use(valid ? once : read(key));
    return { set: function (v) { write(key, v); use(v); }, get: function () { return read(key); } };
  }
  themes.restore = function (key, root) { setBuiltIn(root || document.documentElement, read(key || "az-theme")); };

  global.AzimuthKit = {
    icon: icon, toast: toast, lights: lights, sliders: sliders, themes: themes,
    set sprite(url) { SPRITE = url || ""; }, get sprite() { return SPRITE; }
  };
})(typeof window !== "undefined" ? window : this);
