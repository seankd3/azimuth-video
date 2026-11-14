"""python -m footage.app [EDIT.otio | CLIP ...]: the Azimuth Video window, to cut, trim and frame an edit.

Open an edit, or clips to start a new edit in ~/Videos/Edits. Every change is written to the edit as it is made. The
render runs in heavy's media lane and survives the window.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def shader() -> str:
    """The LUT shader, compiled for Qt's renderers once per change of its source."""
    from .backend import CACHE
    out = CACHE / "lut.frag.qsb"
    if not out.exists() or out.stat().st_mtime < (HERE / "lut.frag").stat().st_mtime:
        out.parent.mkdir(parents=True, exist_ok=True)
        qsb = Path(sys.executable).parent / "pyside6-qsb"
        subprocess.run([str(qsb), "--glsl", "100es,120,150", "--hlsl", "50", "--msl", "12", "-o", str(out),
                        str(HERE / "lut.frag")], check=True)
    return out.as_uri()


def main() -> int:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine

    from .backend import Backend, Images, Theme
    app = QGuiApplication(sys.argv)
    app.setApplicationName("Azimuth Video")
    app.setDesktopFileName("azimuth-video")
    app.setWindowIcon(QIcon(str(HERE / "icon.svg")))
    theme = Theme()
    backend = Backend(theme)
    engine = QQmlApplicationEngine()
    engine.addImageProvider("av", Images())
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("lutShader", shader())
    engine.load(HERE / "Main.qml")
    if not engine.rootObjects():
        return 1
    if len(sys.argv) > 1:
        backend.open("\n".join(str(Path(a).resolve()) for a in sys.argv[1:]))
    code = app.exec()
    del engine  # the window goes before the backend it reads
    return code


if __name__ == "__main__":
    sys.exit(main())
