"""python -m footage: file finished clips from the Ingest inbox into the Library, then fill each clip's sidecar.

Each pass owns one sidecar section and fills it where it is missing or stale; a failed clip is retried next run.
"""
import argparse
import fcntl
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import describe, library, people, probe, sidecar


@dataclass
class Pass:
    section: str
    run: Callable[[Path, dict], dict]
    stale: Callable[[dict], bool]
    workers: int
    available: Callable[[], bool] = lambda: True


def _listen(clip, sc):
    from . import listen  # heavy model imports only when this pass has work
    return listen.listen(clip, sc)


def _focus_version():
    from . import focus
    return focus.VERSION


def _focus(clip, sc):
    from . import focus
    return focus.focus(clip, sc)


def _measure_version():
    from . import measure
    return measure.VERSION


def _measure(clip, sc):
    from . import measure
    return measure.measure(clip, sc)


PASSES = [
    # Two requests keep the model busy while the next frames are cut. A changed squeeze means new frames.
    Pass("description", describe.describe,
         lambda sc: sc["assumed"]["squeeze"] is not None and sc.get("description", {}).get("squeeze_used") != sc["assumed"]["squeeze"],
         2, describe.available),
    Pass("transcript", _listen, lambda sc: "transcript" not in sc, 1),
    Pass("measured", _measure, lambda sc: sc.get("measured", {}).get("v") != _measure_version(), 4),
    Pass("focus", _focus, lambda sc: sc.get("focus", {}).get("v") != _focus_version(), 2),  # reads every frame on the GPU decoder
]


def fill(lib: Path, p: Pass, report: list) -> None:
    todo = []
    for clip in library.clips(lib):
        try:
            sc = sidecar.read(clip)
            if sc is None:
                report.append(("no sidecar (filed by hand?)", clip.name, clip.parent))
            elif not probe.unchanged(clip, sc["facts"]):
                report.append((f"no {p.section}: bytes differ from its sidecar", clip.name, clip.parent.name))
            elif p.section == "description" and sc["assumed"]["squeeze"] is None:
                report.append(("needs squeeze set in its sidecar", clip.name, clip.parent))
            elif p.stale(sc):
                todo.append(clip)
        except Exception as e:
            report.append((f"no {p.section}", f"{clip.parent.name}/{clip.name}", str(e)[:160]))
    if todo and not p.available():
        report.append((f"no {p.section}: its model is not available", f"{len(todo)} clips", None))
        return

    def job(clip):
        sc = sidecar.read(clip)  # fresh, so this write keeps every other section
        return clip, {**sc, p.section: p.run(clip, sc)}

    with ThreadPoolExecutor(p.workers) as pool:
        jobs = [pool.submit(job, clip) for clip in todo]
        for i, done in enumerate(as_completed(jobs), 1):
            try:
                clip, sc = done.result()
                sidecar.write(clip, sc)
                report.append((p.section, clip.name, clip.parent.name))
            except Exception as e:  # the clip keeps its gap and the next run retries it
                report.append((f"{p.section} failed", "", repr(e)[:200]))
            print(f"  {p.section} {i}/{len(todo)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(prog="footage")
    ap.add_argument("--ingest", type=Path, default=Path.home() / "Videos/Ingest")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    a = ap.parse_args()
    # Analysis takes only what the desktop leaves: idle CPU scheduling (and with it idle disk priority), inherited by ffmpeg.
    os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    a.library.mkdir(parents=True, exist_ok=True)
    with open(a.library / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another footage run is using this Library.")
        report: list = []
        library.file_inbox(a.ingest, a.library, report)
        for p in PASSES:
            fill(a.library, p, report)
        people.build(a.library, report)
    counts: dict = {}
    for what, *_ in report:
        counts[what] = counts.get(what, 0) + 1
    for what, name, detail in report:
        if what not in ["filed", "people"] + [p.section for p in PASSES]:
            print(f"{what}: {name} {detail or ''}")
    print("; ".join(f"{k}: {v}" for k, v in counts.items()) or "nothing to do")
    for what, name, detail in report:
        if what == "people":
            print(f"people: {name}, {detail}")


if __name__ == "__main__":
    main()
