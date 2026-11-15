"""azimuth_qt: the Azimuth design system for a PySide6 Qt Quick app.

Vendored with the QML kit at <bundle>/qml/Azimuth/, beside the bundle's themes/, tokens.json, icons.json, mark.svg
and fonts/. Do not edit the vendored copy; change azimuth-design and re-vendor.

    import azimuth_qt
    theme = azimuth_qt.setup(picked="system", on_pick=save)   # after the QGuiApplication, before any engine
    engine = QQmlApplicationEngine()
    azimuth_qt.install(engine)                                # lets it import Azimuth

and in QML:

    import Azimuth as Az
    Rectangle { color: Az.Theme.panel; radius: Az.Theme.radius.panel }
    Az.Button { text: "Render"; kind: "go"; icon.name: "render" }

`Theme` (the singleton) carries every colour token as a property (camelCase: panelRaised, text2, accentInk), bound to
the chosen theme file and retinted live; the measures, type and motion from tokens.json; the icon paths from
icons.json; and the text styles as fonts (`Theme.fonts.button`). The choice is "system" (the live Omarchy theme if
there is one, else Azimuth Dark or Light following the system) or a built-in theme's id. `Theme.choose(id)` changes it
and calls on_pick(id), so the app can remember it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlEngine, qmlRegisterSingletonInstance

HERE = Path(__file__).resolve().parent  # <bundle>/qml/Azimuth
URI = "Azimuth"
SYSTEM = "system"


def _bundle(root: Path | None) -> Path:
    return Path(root) if root else HERE.parent.parent


def _chooser(bundle: Path):
    """The bundle's azimuth_theme module, loaded from its file (it reads XDG_STATE_HOME as it loads)."""
    spec = importlib.util.spec_from_file_location("azimuth_theme_" + str(abs(hash(str(bundle)))),
                                                  bundle / "azimuth_theme.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def camel(token: str) -> str:
    """panel-raised -> panelRaised, text-2 -> text2: a token's name as a QML property."""
    head, *rest = token.split("-")
    return head + "".join(w[:1].upper() + w[1:] for w in rest)


def css_color(text: str) -> QColor:
    """A tokens.toml colour: #rrggbb, or rgba(r, g, b, a)."""
    m = re.fullmatch(r"\s*rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)\s*", text)
    if m:
        r, g, b = (int(float(v)) for v in m.groups()[:3])
        return QColor(r, g, b, round(float(m.group(4) or 1) * 255))
    return QColor(text)


def bezier(ease: str) -> list[float]:
    """cubic-bezier(x1, y1, x2, y2) as QML's Easing.BezierSpline curve."""
    nums = [float(v) for v in re.findall(r"-?\d*\.?\d+", ease)]
    return (nums[:4] if len(nums) >= 4 else [0.25, 0.1, 0.25, 1.0]) + [1.0, 1.0]


def load_fonts(bundle: Path) -> list[str]:
    """Add the bundled fonts (woff2) to the application. Returns the families added."""
    families = set()
    for f in sorted((bundle / "fonts").glob("*.woff2")) + sorted((bundle / "fonts").glob("*.ttf")):
        fid = QFontDatabase.addApplicationFont(str(f))
        if fid >= 0:
            families.update(QFontDatabase.applicationFontFamilies(fid))
    return sorted(families)


def mark_paths(bundle: Path) -> dict:
    """The compass mark (mark.svg) as path data for QML: ring and ticks stroked, the needle filled."""
    ns = "{http://www.w3.org/2000/svg}"
    out = {"ring": "", "ticks": "", "needle": "", "size": 32, "stroke": 1.2}
    try:
        root = ET.parse(bundle / "mark.svg").getroot()
    except (OSError, ET.ParseError):
        return out
    out["size"] = float(root.get("viewBox", "0 0 32 32").split()[2])
    out["stroke"] = float(root.get("stroke-width", 1.2))
    for el in root:
        if el.tag == ns + "circle":
            cx, cy, r = (float(el.get(k)) for k in ("cx", "cy", "r"))
            out["ring"] = f"M{cx + r} {cy}A{r} {r} 0 1 1 {cx - r} {cy}A{r} {r} 0 1 1 {cx + r} {cy}Z"
        elif el.tag == ns + "path":
            out["needle" if el.get("fill") else "ticks"] = el.get("d", "")
    return out


def _token_names() -> list[str]:
    """Every colour token, from a built-in theme file of the bundle this module sits in."""
    for p in sorted((_bundle(None) / "themes").glob("*.json")):
        try:
            return list(json.loads(p.read_text())["colors"])
        except (OSError, ValueError, KeyError):
            continue
    return []


class Theme(QObject):
    """The Theme singleton. Its colours are one notified property per colour token, named in the bundle's theme files."""

    changed = Signal()

    def __init__(self, bundle: Path, picked: str | None = None, on_pick=None):
        super().__init__()
        self._bundle = bundle
        self._az = _chooser(bundle)
        self._on_pick = on_pick
        self._choice = picked if picked in self._ids() else SYSTEM
        tk = json.loads((bundle / "tokens.json").read_text())
        self._tokens = tk
        icons = json.loads((bundle / "icons.json").read_text())
        self._icons, self._stroke = icons["icons"], float(icons.get("stroke", 1.4))
        self._mark = mark_paths(bundle)
        self._families = load_fonts(bundle)
        self._media = {camel(k.replace("_", "-")): css_color(v) for k, v in tk.get("media", {}).items()}
        self._t: dict = {}
        self._fonts: dict = {}

        # The live theme file is replaced atomically, so watch its folder (or the nearest one that exists).
        self._watch = QFileSystemWatcher(self)
        self._watch.directoryChanged.connect(lambda _: self._soon.start())
        self._watch.fileChanged.connect(lambda _: self._soon.start())
        self._soon = QTimer(self, singleShot=True, interval=80, timeout=self.reload)
        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _: self.reload())
        self.reload()

    # Choosing

    def _ids(self) -> list[str]:
        return [SYSTEM] + list(self._az.built_ins())

    def _system_dark(self) -> bool:
        return QGuiApplication.styleHints().colorScheme() != Qt.ColorScheme.Light

    def _rewatch(self):
        live = self._az.RUNTIME
        want = [str(p) for p in (live.parent, live) if p.exists()]
        if not want:  # no live theme yet: watch the nearest folder that exists, for it to appear
            p = live.parent
            while not p.exists() and p != p.parent:
                p = p.parent
            want = [str(p)]
        have = self._watch.directories() + self._watch.files()
        if sorted(want) != sorted(have):
            if have:
                self._watch.removePaths(have)
            self._watch.addPaths(want)

    @Slot()
    def reload(self):
        """Choose again and retint: on a change of the live theme, the system's dark or light, or the pick."""
        self._rewatch()
        t = self._az.choose(None if self._choice == SYSTEM else self._choice, self._system_dark())
        if t == self._t:
            return
        self._t = t
        self._fonts = {name: self._font(style) for name, style in self._tokens["type"].items()}
        self.changed.emit()

    @Slot(str)
    def choose(self, choice: str):
        """Choose "system" or a built-in theme's id; the app's on_pick remembers it."""
        choice = choice if choice in self._ids() else SYSTEM
        if choice == self._choice:
            return
        self._choice = choice
        self._t = {}
        self.reload()
        if self._on_pick:
            self._on_pick(choice)

    def _choices(self) -> list[dict]:
        live = self._az.runtime()
        system = f"System ({live['name']})" if live else "System"
        return [{"id": SYSTEM, "name": system}] + [{"id": i, "name": t["name"]} for i, t in self._az.built_ins().items()]

    # Type

    def _family(self, face: str) -> str:
        """The theme's family for a face (Omarchy's mono when it is installed), else the bundled one."""
        want = (self._t.get("font") or {}).get(face) or self._tokens["font"][face]
        return want if QFontDatabase.hasFamily(want) else self._tokens["font"][face]

    def _font(self, s: dict) -> QFont:
        f = QFont(self._family(s["face"]))
        screen = QGuiApplication.primaryScreen()
        dpi = screen.logicalDotsPerInch() if screen else 96.0
        f.setPointSizeF(float(s["size"]) * 72.0 / dpi)  # fractional pixel sizes (9.5, 10.5) survive
        f.setWeight(QFont.Weight(int(s["weight"])))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(s["tracking"]) * float(s["size"]))
        f.setCapitalization(QFont.Capitalization.AllUppercase if s["caps"] else QFont.Capitalization.MixedCase)
        return f

    @Slot(str, result=QFont)
    def font(self, style: str) -> QFont:
        """A text style as a font (not notified: bind to Theme.fonts[style] to follow theme changes)."""
        return self._fonts.get(style) or self._font(self._tokens["type"]["body"])

    # Helpers for QML

    @Slot(QColor, float, result=QColor)
    def alpha(self, c: QColor, a: float) -> QColor:
        out = QColor(c)
        out.setAlphaF(max(0.0, min(1.0, a)))
        return out

    @Slot(str, result=QColor)
    def color(self, token: str) -> QColor:
        return QColor(self._t.get("colors", {}).get(token, "#000000"))

    def _c(self, token: str) -> QColor:
        return QColor(self._t.get("colors", {}).get(token, "#000000"))

    def _prop(kind, fn, notify=changed):
        return Property(kind, fn, notify=notify)

    def _const(kind, fn):
        return Property(kind, fn, constant=True)

    name = _prop(str, lambda self: self._t.get("name", ""))
    themeId = _prop(str, lambda self: self._t.get("id", ""))
    source = _prop(str, lambda self: self._t.get("source", ""))
    mode = _prop(str, lambda self: self._t.get("mode", "dark"))
    dark = _prop(bool, lambda self: self._t.get("mode", "dark") != "light")
    choice = _prop(str, lambda self: self._choice)
    choices = _prop("QVariantList", lambda self: self._choices())
    fontSans = _prop(str, lambda self: self._family("sans"))
    fontMono = _prop(str, lambda self: self._family("mono"))
    fonts = _prop("QVariantMap", lambda self: dict(self._fonts))
    # Floats cast one shadow: black at 35 % in dark, 12 % in light (components.md, Float).
    shadow = _prop(QColor, lambda self: QColor(0, 0, 0, 89 if self._t.get("mode", "dark") != "light" else 31))

    tokens = _const("QVariantMap", lambda self: self._tokens)
    size = _const("QVariantMap", lambda self: self._tokens["size"])
    space = _const("QVariantMap", lambda self: self._tokens["space"])
    radius = _const("QVariantMap", lambda self: self._tokens["radius"])
    motion = _const("QVariantMap", lambda self: {k: v for k, v in self._tokens["motion"].items() if not isinstance(v, str)})
    ease = _const("QVariantList", lambda self: bezier(self._tokens["motion"].get("ease", "")))
    type = _const("QVariantMap", lambda self: self._tokens["type"])
    icons = _const("QVariantMap", lambda self: self._icons)
    stroke = _const(float, lambda self: self._stroke)
    mark = _const("QVariantMap", lambda self: self._mark)
    scrim = _const(QColor, lambda self: self._media.get("scrim", QColor(0, 0, 0, 158)))
    surroundGrey = _const(QColor, lambda self: self._media.get("surroundGrey", QColor(119, 119, 119)))
    surroundLight = _const(QColor, lambda self: self._media.get("surroundLight", QColor(200, 200, 200)))
    families = _const("QStringList", lambda self: self._families)

    # One property per colour token (panel-raised -> panelRaised), made here so Qt sees them with the class.
    for _token in _token_names():
        vars()[camel(_token)] = Property(QColor, (lambda k: lambda self: self._c(k))(_token), notify=changed)
    del _token


_theme: Theme | None = None


def setup(picked: str | None = None, on_pick=None, bundle: Path | None = None) -> Theme:
    """Load the fonts and make the Theme singleton. Call it once the QGuiApplication exists and before the first
    QQmlEngine is made: Qt takes a type registered after an engine exists only half-way.

    One Theme serves every engine in the process: a second call re-uses it (and takes a new pick and on_pick).
    """
    global _theme
    if _theme is None:
        _theme = Theme(_bundle(bundle), picked, on_pick)
        qmlRegisterSingletonInstance(Theme, URI, 1, 0, "Theme", _theme)
    else:
        _theme._on_pick = on_pick
        if picked:
            _theme._choice = picked if picked in _theme._ids() else SYSTEM
            _theme.reload()
    return _theme


def install(engine: QQmlEngine) -> Theme:
    """Let `engine` import Azimuth. setup() must have run before the engine was made."""
    if _theme is None:
        raise RuntimeError("azimuth_qt.setup() runs before the first QQmlEngine is made")
    engine.addImportPath(str(HERE.parent))
    return _theme
