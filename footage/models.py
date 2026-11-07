"""Where the toolkit's local models live, and what identifies one: its files' names and sizes.

FOLDER holds read-only snapshots, and nothing replaces a file in it: a new model or version is published under a new
name, after `chmod u+w` on the folder. So the files a pass is identified by are the files it loads, and sizes, not
hashes, are enough; checking whether a section is current never reads gigabytes of weights.
"""
from functools import cache
from pathlib import Path

FOLDER = Path.home() / ".local/share/footage/models"


def identity(*paths: Path) -> dict:
    """Name and size of each model file; a folder stands for every file in it."""
    out = {}
    for p in paths:
        for f in [p] if p.is_file() else sorted(p.rglob("*")):
            if f.is_file():
                out[str(f.relative_to(p.parent))] = f.stat().st_size
    return out


@cache
def providers() -> list:
    """Where ONNX models run: the GPU when onnxruntime-gpu is installed, else the CPU. onnxruntime-gpu finds the CUDA and
    cuDNN libraries of NVIDIA's wheels only once they are preloaded; without that a CUDA session fails, not falls back."""
    import onnxruntime as rt
    if "CUDAExecutionProvider" not in rt.get_available_providers():
        return ["CPUExecutionProvider"]
    rt.preload_dlls()
    return ["CUDAExecutionProvider", "CPUExecutionProvider"]
