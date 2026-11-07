"""python -m footage: file finished clips from the Ingest inbox into the Library, then fill each clip's sidecar.

Each pass (passes.py) owns one sidecar section and fills it where it is missing or out of date; a failed clip is
retried next run.
"""
import argparse
import fcntl
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import describe, develop, idle, library, people, probe, sidecar
from .passes import PASSES, Pass, current


def fill(lib: Path, p: Pass, report: list) -> None:
    todo = []
    for clip in library.clips(lib):
        try:
            sc = sidecar.read(clip)
            if sc is None:
                report.append(("no sidecar (filed by hand?)", clip.name, clip.parent))
            elif not probe.unchanged(clip, sc["facts"]):  # filing's scan has confirmed a moved mtime by hash
                report.append((f"no {p.section}: bytes differ from its sidecar", clip.name, clip.parent.name))
            elif p.section == "description" and sc["assumed"]["squeeze"] is None:
                report.append(("needs squeeze set in its sidecar", clip.name, clip.parent))
            elif not current(sc, p.section):
                todo.append(clip)
        except Exception as e:
            report.append((f"no {p.section}", f"{clip.parent.name}/{clip.name}", str(e)[:160]))

    def job(clip):
        sc = sidecar.read(clip)
        return clip, p.identity(sc), p.run(clip, sc)

    waiting = 0
    with ThreadPoolExecutor(p.workers) as pool:
        jobs = [pool.submit(job, clip) for clip in todo]
        for i, done in enumerate(as_completed(jobs), 1):
            try:
                clip, made_from, section = done.result()
                # Written into the sidecar as it is now, so an edit made during the pass stays; a result whose inputs
                # changed meanwhile is dropped, and the next run redoes it.
                same = lambda sc: sc is not None and probe.unchanged(clip, sc["facts"]) and p.identity(sc) == made_from
                if section is None:  # a question now waits for its answer
                    waiting += 1
                elif sidecar.update(clip, lambda sc: {**sc, p.section: {"id": made_from, **section}} if same(sc) else None):
                    report.append((p.section, clip.name, clip.parent.name))
                else:
                    report.append((f"no {p.section}: its inputs changed during the pass", clip.name, clip.parent.name))
            except Exception as e:  # the clip keeps its gap and the next run retries it
                report.append((f"{p.section} failed", "", repr(e)[:200]))
            print(f"  {p.section} {i}/{len(todo)}", flush=True)
    if waiting:
        report.append((f"no {p.section}: waiting for answers", f"{waiting} clips", None))


def main() -> None:
    ap = argparse.ArgumentParser(prog="footage")
    ap.add_argument("--ingest", type=Path, default=Path.home() / "Videos/Ingest")
    ap.add_argument("--library", type=Path, default=Path.home() / "Videos/Library")
    a = ap.parse_args()
    idle()
    a.library.mkdir(parents=True, exist_ok=True)
    with open(a.library / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another footage run is using this Library.")
        report: list = []
        library.file_inbox(a.ingest, a.library, report)
        develop.build(a.library, report)
        for p in PASSES:
            fill(a.library, p, report)
        describe.retire(a.library)
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
