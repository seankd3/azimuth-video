"""Filing: move a finished clip from the inbox into its shooting-day folder, never overwriting anything.

Ownership changes hands in atomic steps on one filesystem:
1. claim: rename the finished inbox file into Ingest/.claimed/. From then on this run owns it, and its inbox
   name is free for new arrivals, which this run will never delete.
2. publish: hard-link the claimed file into Library/<day>/ under a free name, then write its sidecar.
3. release: remove the claimed name.
A crash leaves the file in .claimed/, and the next run finishes it from there.
"""
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, probe, sidecar


def timezone() -> ZoneInfo | None:
    """The configured timezone for shooting days, or None for the system's local time."""
    name = config.load().get("timezone")
    return ZoneInfo(name) if name else None
CLAIMED = ".claimed"


def day_of(captured_utc: str) -> str:
    return datetime.fromisoformat(captured_utc).astimezone(timezone()).date().isoformat()


def clips(library: Path) -> list[Path]:
    return sorted(p for p in library.glob("*/*") if probe.is_video(p))


def scan(library: Path, report: list) -> tuple[dict, dict]:
    """Library clips by inode (to finish interrupted publishes) and by content hash (to spot duplicates).
    Only a clip whose bytes still match its sidecar counts as holding that content."""
    by_inode, by_hash = {}, {}
    for p in clips(library):
        try:
            st = p.stat()
            by_inode[(st.st_dev, st.st_ino)] = p
            sc = sidecar.read(p)
            if sc is None:
                continue
            if confirm(p, sc):
                by_hash[sc["facts"]["sha256"]] = p
            else:
                report.append(("bytes differ from its sidecar", p.name, p.parent.name))
        except Exception as e:  # one bad clip or sidecar must not stop the rest
            report.append(("unreadable sidecar or clip", f"{p.parent.name}/{p.name}", str(e)[:160]))
    return by_inode, by_hash


def confirm(clip: Path, sc: dict) -> bool:
    """Whether the clip still holds the bytes its sidecar describes. A clip whose mtime alone moved (copied, touched) is
    confirmed by its hash, and the new mtime is written back so the cheap check holds again."""
    f = sc["facts"]
    if probe.unchanged(clip, f):
        return True
    st = clip.stat()
    if st.st_size != f["size"] or probe.sha256(clip) != f["sha256"]:
        return False
    sidecar.write(clip, {**sc, "facts": {**f, "mtime_ns": st.st_mtime_ns}})
    return True


def link_free_name(src: Path, folder: Path) -> Path:
    """Hard-link src into folder under its own name, or NAME-2, NAME-3...; os.link never replaces an existing file."""
    stem, ext = src.stem, src.suffix
    for n in range(1, 1000):
        dest = folder / (src.name if n == 1 else f"{stem}-{n}{ext}")
        if sidecar.path_for(dest).exists():
            continue  # a sidecar without its clip still owns the name
        try:
            os.link(src, dest)
        except FileExistsError:
            continue
        sidecar.sync_dir(folder)
        return dest
    raise RuntimeError(f"no free name for {src.name} in {folder}")


def identity(p: Path) -> tuple:
    st = p.stat()
    return st.st_ino, st.st_size, st.st_mtime_ns


def release(claimed: Path) -> None:
    os.unlink(claimed)
    sidecar.sync_dir(claimed.parent)


def entry(f: dict) -> dict:
    return {"facts": f, "assumed": probe.assumed(f), "day_timezone": str(timezone() or datetime.now().astimezone().tzinfo)}


def publish(claimed: Path, f: dict | None, library: Path, by_inode: dict, by_hash: dict, report: list) -> None:
    st = claimed.stat()
    twin = by_inode.get((st.st_dev, st.st_ino))
    if twin is not None:  # an earlier run linked it, then stopped
        if sidecar.read(twin) is None:
            sidecar.write(twin, entry(probe.facts(twin) | {"original_name": claimed.name}))
        release(claimed)
        report.append(("finished an interrupted move", claimed.name, twin))
        return
    f = f or probe.facts(claimed)
    if f["sha256"] in by_hash:
        report.append(("duplicate, left in Ingest/.claimed", claimed.name, by_hash[f["sha256"]]))
        return
    folder = library / day_of(f["captured_utc"])
    folder.mkdir(exist_ok=True)
    dest = link_free_name(claimed, folder)
    sidecar.write(dest, entry(f))
    release(claimed)
    by_hash[f["sha256"]] = dest
    report.append(("filed", claimed.name, dest))


def file_inbox(ingest: Path, library: Path, report: list) -> None:
    if os.stat(ingest).st_dev != os.stat(library).st_dev:
        raise SystemExit("Ingest and Library must be on one filesystem, so filing is a rename and never a copy.")
    claim_dir = ingest / CLAIMED
    claim_dir.mkdir(exist_ok=True)
    by_inode, by_hash = scan(library, report)
    left_claimed = sorted(claim_dir.iterdir())
    listed = sorted(p for p in ingest.iterdir() if probe.is_video(p))
    held = probe.open_files()  # after listing: a listed file is either still being written now, or finished
    for claimed in left_claimed:
        try:
            ok, why = probe.ready(claimed, held)
            if not ok:
                report.append(("waiting in Ingest/.claimed", claimed.name, why))
                continue
            publish(claimed, None, library, by_inode, by_hash, report)
        except Exception as e:  # one bad file must not stop the rest
            report.append(("could not file", claimed.name, repr(e)[:200]))
    for other in sorted(set(ingest.iterdir()) - set(listed)):
        if not other.name.startswith("."):
            report.append(("left alone (not a video)", other.name, None))
    for src in listed:
        try:
            ok, why = probe.ready(src, held)
            if not ok:
                report.append(("waiting", src.name, why))
                continue
            before = identity(src)
            f = probe.facts(src)
            if f["sha256"] in by_hash:
                report.append(("duplicate, left in Ingest", src.name, by_hash[f["sha256"]]))
                continue
            if not f["captured_utc"]:
                report.append(("no capture time, left in Ingest", src.name, None))
                continue
            claimed = claim_dir / src.name
            if claimed.exists() or identity(src) != before:
                report.append(("changed while filing, left in Ingest", src.name, None))
                continue
            os.rename(src, claimed)  # the lock makes this run the only writer of .claimed/
            sidecar.sync_dir(ingest)
            if identity(claimed) != before:
                report.append(("replaced while filing, left in Ingest/.claimed", src.name, None))
                continue
            publish(claimed, f, library, by_inode, by_hash, report)
        except Exception as e:  # one bad file must not stop the rest
            report.append(("could not file", src.name, repr(e)[:200]))
