/* azimuth-theme.js: apply an Azimuth theme file to a page, and follow one as it changes.
 *
 *   AzimuthTheme.apply(theme)          set the page's --az-* colours, mode and fonts from a theme file
 *   AzimuthTheme.follow(url, {every})  fetch a theme file now and again, applying each change
 *                                      (a local app serves ~/.local/state/azimuth/theme.json at url)
 *   AzimuthTheme.clear()               back to azimuth.css's built-in themes
 *
 * azimuth.css alone themes a page; this is only for themes chosen at run time.
 */
(function (global) {
  "use strict";
  var FORMAT = 1;
  var applied = [];

  function apply(theme, root) {
    root = root || document.documentElement;
    if (!theme || theme.format > FORMAT || !theme.colors) return false;
    clear(root);
    Object.keys(theme.colors).forEach(function (k) {
      root.style.setProperty("--az-" + k, theme.colors[k]);
      applied.push("--az-" + k);
    });
    if (theme.font && theme.font.mono) {
      root.style.setProperty("--az-mono", '"' + theme.font.mono + '", "JetBrains Mono", ui-monospace, monospace');
      applied.push("--az-mono");
    }
    root.style.setProperty("color-scheme", theme.mode);
    applied.push("color-scheme");
    root.setAttribute("data-theme", theme.id);
    root.setAttribute("data-mode", theme.mode);
    return true;
  }

  function clear(root) {
    root = root || document.documentElement;
    applied.forEach(function (p) { root.style.removeProperty(p); });
    applied = [];
    root.removeAttribute("data-theme");
    root.removeAttribute("data-mode");
  }

  function follow(url, opts) {
    var every = (opts && opts.every) || 1500, last = null, stopped = false;
    function tick() {
      if (stopped) return;
      fetch(url, { cache: "no-store" })
        .then(function (r) { return r.ok ? r.text() : r.status === 404 ? "" : null; })
        .then(function (text) {
          // stopped while the fetch was out: the owner picked another theme, so leave theirs
          if (stopped || text === null || text === last) return;
          last = text;
          if (text === "") { clear(); return; }  // the live theme went away: back to the system's
          try { apply(JSON.parse(text)); } catch (e) { last = null; /* half-written: next tick */ }
        })
        .catch(function () {})
        .then(function () { setTimeout(tick, every); });
    }
    tick();
    return function stop() { stopped = true; };
  }

  global.AzimuthTheme = { apply: apply, clear: clear, follow: follow, FORMAT: FORMAT };
})(typeof window !== "undefined" ? window : this);
