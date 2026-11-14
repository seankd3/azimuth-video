"""What the window reads and calls: the edit through its door, the preview's geometry and grade, and renders.

Everything the window shows is computed from the edit on each change (`shots`), so the view depends only on the edit.
"""
import hashlib
import re
import subprocess
import time
import tomllib
from fractions import Fraction
from functools import cache
from pathlib import Path

import numpy as np
import opentimelineio as otio
from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QProcess, QSize, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

from .. import grade, render, view
from . import edit as E

CACHE = Path.home() / ".cache/azimuth-video/app"
THEME = Path.home() / ".local/state/omarchy/current/theme/colors.toml"
DARK = {"background": "#101010", "foreground": "#e8e8e8", "accent": "#d9a441", "muted": "#8a8a8a",
        "lighter_background": "#1c1c1c", "selection": "#333333", "red": "#e06c5a"}
FOOTAGE = str(Path.home() / ".local/bin/footage")
HEAVY = str(Path.home() / ".local/bin/heavy")


class Theme(QObject):
    """The Omarchy theme's colours, followed live, or a dark default off Omarchy."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self._colors = dict(DARK)
        self._watch = QFileSystemWatcher([str(THEME.parent)] if THEME.parent.exists() else [])
        self._watch.directoryChanged.connect(lambda _: QTimer.singleShot(80, self._load))
        self._load()

    def _load(self):
        try:
            self._colors = {**DARK, **{k: v for k, v in tomllib.loads(THEME.read_text()).items()
                                       if isinstance(v, str) and v.startswith("#")}}
        except (OSError, tomllib.TOMLDecodeError):
            self._colors = dict(DARK)
        self.changed.emit()

    def _c(name, changed=changed):
        return Property(QColor, lambda self: QColor(self._colors[name]), notify=changed)

    background, foreground, accent, muted = _c("background"), _c("foreground"), _c("accent"), _c("muted")
    raised, selection, warning = _c("lighter_background"), _c("selection"), _c("red")


@cache
def shot_facts(path: str, stamp: float) -> dict:
    """A clip's sidecar for the grade (render.read, with its person), or its plain facts when it isn't measured."""
    try:
        return render.read(Path(path), ("measured",))
    except SystemExit:
        return E.facts(Path(path))


def facts(path: str) -> dict:
    return shot_facts(path, Path(path + ".json").stat().st_mtime)


class Images(QQuickImageProvider):
    """image://av/lut/LOOK/PATH: a shot's print as a 33^3 LUT packed in a 2D image (blue slices side by side).
    image://av/thumb/SECONDS/PATH: one desqueezed frame of a clip, 90 rows tall, cached on disk as PNG (the JPEG
    encoder refuses limited-range video)."""

    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image, QQuickImageProvider.Flag.ForceAsynchronousImageLoading)

    def requestImage(self, id: str, size: QSize, requested: QSize) -> QImage:
        kind, arg, path = id.split("/", 2)
        path = "/" + QUrl.fromPercentEncoding(path.encode()).lstrip("/")
        image = lut(path, arg) if kind == "lut" else thumb(path, float(arg))
        size.setWidth(image.width())
        size.setHeight(image.height())
        return image


@cache
def _lut(path: str, look: str, stamp: float) -> QImage:
    sc = shot_facts(path, stamp)
    n = grade.SIZE
    if "measured" not in sc:  # not measured yet: show the camera's code values as they are
        g = np.linspace(0, 1, n)
        b, gg, r = np.meshgrid(g, g, g, indexing="ij")
        table = np.stack([r, gg, b], -1).reshape(-1, 3)
    else:
        table = grade.print_lut(sc, grade.look(look))
    cube = table.reshape(n, n, n, 3)  # [blue, green, red]
    packed = np.concatenate([cube[b] for b in range(n)], axis=1)  # rows green, columns blue * n + red
    rgba = np.concatenate([packed, np.ones(packed.shape[:2] + (1,))], -1)
    data = np.ascontiguousarray((np.clip(rgba, 0, 1) * 65535).round().astype(np.uint16))
    return QImage(data.data, n * n, n, n * n * 8, QImage.Format.Format_RGBA64).copy()


def lut(path: str, look: str) -> QImage:
    return _lut(path, look, Path(path + ".json").stat().st_mtime)


def thumb(path: str, t: float) -> QImage:
    out = CACHE / "thumbs" / (hashlib.sha1(f"{path}@{t:.2f}".encode()).hexdigest() + ".png")
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        s = view.squeeze(facts(path))
        part = out.with_suffix(".part.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", f"scale=trunc(90*dar*{s}/2)*2:90", str(part)], check=False)
        if part.exists():
            part.replace(out)
    return QImage(str(out)) if out.exists() else QImage(160, 90, QImage.Format.Format_RGB32)


class Backend(QObject):
    changed = Signal()
    renderChanged = Signal()
    message = Signal(str)

    def __init__(self, theme: Theme):
        super().__init__()
        self._theme, self._edit, self._shots, self._watch = theme, None, [], QFileSystemWatcher()
        self._watch.fileChanged.connect(self._outside)
        self._render, self._progress, self._job = None, -1.0, ""

    # The edit

    @Slot(str)
    def open(self, target: str):
        """Open an edit, or start one from clips (a new edit in ~/Videos/Edits)."""
        paths = [Path(QUrl(p).toLocalFile() if p.startswith("file:") else p).expanduser() for p in target.split("\n") if p]
        try:
            if paths[0].suffix == ".otio":
                self._edit = E.Edit(paths[0])
            else:
                folder = Path.home() / "Videos/Edits" / f"{time.strftime('%Y-%m-%d')} {paths[0].stem}"
                folder.mkdir(parents=True, exist_ok=True)
                out = folder / f"{paths[0].stem}.otio"
                self._edit = E.Edit(out) if out.exists() else E.Edit(out, E.new(paths))
        except (OSError, ValueError) as e:
            self.message.emit(str(e))
            return
        if self._watch.files():
            self._watch.removePaths(self._watch.files())
        self._watch.addPath(str(self._edit.path))
        self._refresh()

    def _outside(self, path: str):
        if not Path(path).exists():  # replaced by a rename: watch the new file once it is there
            QTimer.singleShot(50, lambda: self._outside(path))
            return
        if path not in self._watch.files():
            self._watch.addPath(path)
        if self._edit.outside():
            self._refresh()

    def _do(self, action, *args):
        if self._edit is None:
            return
        try:
            if self._edit.do(action, *args):
                self._refresh()
        except (OSError, ValueError, IndexError) as e:
            self.message.emit(str(e))

    def _refresh(self):
        """The shots as the window shows them: each clip of the picture track, where the render places it."""
        t = self._edit.timeline
        track, a, shots = E.picture(t), E.aspect(t), []
        for i, clip in enumerate(track):
            if not isinstance(clip, otio.schema.Clip):
                continue
            r, path = clip.source_range, E.media(clip)
            start, dur, at = r.start_time.to_seconds(), r.duration.to_seconds(), track.range_of_child(clip).start_time.to_seconds()
            item = {"index": i, "at": at, "start": start, "duration": dur, "name": clip.name, "path": "",
                    "length": dur, "fps": 30.0, "title": "", "geometry": {}, "framing": {}}
            if path is None:
                item["title"] = str(getattr(clip.media_reference, "parameters", {}).get("text", "Title"))
            else:
                sc = facts(str(path))
                framing = view.frame(sc, clip.metadata.get("footage", {}).get("framing"), a)
                item.update(path=str(path), length=sc["facts"]["duration"], fps=float(Fraction(sc["facts"]["fps"])),
                            framing=framing, geometry=geometry(sc, framing, a), graded="measured" in sc,
                            oval=view.squeeze(sc) ** (-1 if framing["turn"] % 2 else 1))
            shots.append(item)
        self._shots = shots
        self.changed.emit()

    def _p(kind, fn, changed=changed):
        return Property(kind, fn, notify=changed)

    shots = _p("QVariantList", lambda self: self._shots)
    duration = _p(float, lambda self: sum(s["duration"] for s in self._shots))
    name = _p(str, lambda self: self._edit.path.stem if self._edit else "")
    aspect = _p(float, lambda self: E.aspect(self._edit.timeline) if self._edit else view.ASPECT)
    aspectName = _p(str, lambda self: next((n for n, v in E.ASPECTS if v == self._setting("aspect", view.ASPECT)),
                                           str(self._setting("aspect", view.ASPECT))))
    look = _p(str, lambda self: self._setting("look", grade.DEFAULT))
    vignette = _p(float, lambda self: grade.look(self._setting("look", grade.DEFAULT)).vignette or 0.0)
    flat = Property(float, lambda self: grade.VIGNETTE_FLAT, constant=True)
    canUndo = _p(bool, lambda self: bool(self._edit) and self._edit.at > 0)
    canRedo = _p(bool, lambda self: bool(self._edit) and self._edit.at < len(self._edit.history) - 1)
    aspects = Property("QStringList", lambda self: [n for n, _ in E.ASPECTS], constant=True)
    looks = Property("QStringList", lambda self: [lk.name for lk in grade.looks()], constant=True)
    theme = Property(QObject, lambda self: self._theme, constant=True)
    libraryFolder = Property(str, lambda self: str(Path.home() / "Videos/Library"), constant=True)
    editsFolder = Property(str, lambda self: str(Path.home() / "Videos/Edits"), constant=True)

    def _setting(self, key, default):
        return self._edit.timeline.metadata.get("footage", {}).get(key, default) if self._edit else default

    # The window names a shot by its place among the shots; the track can also hold gaps and transitions.

    def _track(self, i: int) -> int:
        return self._shots[i]["index"] if i < len(self._shots) else len(E.picture(self._edit.timeline))

    @Slot(int, float)
    def split(self, i, at): self._do(E.split, self._track(i), at)

    @Slot(int, float, float)
    def trim(self, i, start, end): self._do(E.trim, self._track(i), start, end)

    @Slot(int, int)
    def move(self, i, to): self._do(E.move, self._track(i), self._track(to) if to < i else self._track(to + 1) - 1)

    @Slot(int)
    def remove(self, i): self._do(E.remove, self._track(i))

    @Slot(int, str)
    def add(self, at, path): self._do(E.add, self._track(at), QUrl(path).toLocalFile() if path.startswith("file:") else path)

    @Slot(int, dict)
    def setFraming(self, i, framing):
        self._do(E.frame, self._track(i), {k: framing[k] for k in ("turn", "center", "zoom") if k in framing})

    @Slot(str)
    def setAspect(self, name): self._do(E.setting, "aspect", dict(E.ASPECTS)[name])

    @Slot(str)
    def setLook(self, name): self._do(E.setting, "look", name)

    @Slot()
    def undo(self):
        if self._edit and self._edit.undo():
            self._refresh()

    @Slot()
    def redo(self):
        if self._edit and self._edit.redo():
            self._refresh()

    @Slot(int, dict, result=dict)
    def preview(self, i, framing):
        """The geometry a framing would have, before it is stored: for the frame editor's live drag."""
        s = self._shots[i]
        sc, a = facts(s["path"]), E.aspect(self._edit.timeline)
        f = view.frame(sc, dict(framing), a)
        return {"framing": f, "geometry": geometry(sc, f, a)}

    # Renders

    @Slot()
    def render(self):
        if self._edit is None or self._render is not None:
            return
        self._job = f"render-{re.sub('[^A-Za-z0-9]', '-', self._edit.path.stem)[:40]}-{int(time.time())}"
        subprocess.run([HEAVY, self._job, FOOTAGE, "render", str(self._edit.path)], check=False,
                       cwd=str(self._edit.path.parent))
        self._frames, self._progress, self._master = 0, 0.0, ""
        self._total = sum(round(s["duration"] * s["fps"]) for s in self._shots) or 1
        self._render = QProcess(self)
        self._render.readyReadStandardOutput.connect(self._follow)
        self._render.finished.connect(self._ended)
        self._render.start("journalctl", ["--user", "-f", "-o", "cat", "-u", f"{self._job}-job"])
        self._poll = QTimer(self, interval=1000, timeout=self._check)
        self._poll.start()
        self.renderChanged.emit()

    def _follow(self):
        for line in bytes(self._render.readAllStandardOutput()).decode(errors="replace").splitlines():
            if m := re.search(r": (\d+) frames$", line):
                self._frames = int(m.group(1))
                self._progress = min(self._frames / self._total, 1.0)
                self.renderChanged.emit()
            elif line.strip().endswith(".mp4"):
                self._master = line.strip()

    def _check(self):
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", self._job]).returncode == 0
        if not active:
            self._follow()
            self.message.emit(f"Rendered {Path(self._master).name}" if self._master else
                              f"The render stopped: journalctl --user -u {self._job}-job")
            self._poll.stop()
            self._render.terminate()

    def _ended(self):
        self._render, self._progress = None, -1.0
        self.renderChanged.emit()

    progress = Property(float, lambda self: self._progress, notify=renderChanged)


def geometry(sc: dict, framing: dict, aspect: float) -> dict:
    """Where the window draws a shot's video for its framing, in units of the preview's width: the video's size
    (desqueezed, before the turn), its centre's offset from the preview's centre, and the turn in degrees. The
    frame editor's view of the whole turned frame is the same picture at zoom 1/fit."""
    turn, s = framing["turn"], view.squeeze(sc)
    (fw, fh), (w, _) = view.turned(sc, turn), view.fitted(sc, turn, aspect, framing["zoom"])
    cx, cy = framing["center"]
    W, H = sc["facts"]["width"], sc["facts"]["height"]
    return {"width": W * s / w, "height": H / w, "x": (fw / 2 - cx * fw) / w, "y": (fh / 2 - cy * fh) / w,
            "rotation": 90 * turn, "frameWidth": fw / w, "frameHeight": fh / w}
