#!/usr/bin/env bash
# Install Azimuth Video on a Linux machine (ARM64 or x86-64) with an NVIDIA GPU, or bring an install up to date.
# Every step checks what is already there and does only what is missing, so running it again is safe.
#
#   1. Python: a virtual environment in .venv with the packages in setup/requirements.txt, and dlib built with CUDA.
#   2. Programs: ffmpeg 8.1 with NVDEC and 10-bit x265 (as ffmpeg-gpu), and LibRaw built to read RAW clips over 2 GB.
#   3. Models: each file in setup/models.txt, checked by sha256, and TitaNet-large exported from NVIDIA's release.
#   4. Commands and skills: `footage` and `heavy` in ~/.local/bin, the heavy-job memory limit, the skills linked
#      into Claude Code (and Codex), and a starter config.
#
# It needs uv, curl, a C++ compiler, make and the CUDA toolkit (nvcc). Downloads are about 8 GB.
set -euo pipefail
REPO="$(cd "$(dirname "$0")" && pwd)"
DATA="$HOME/.local/share/footage"
VENDOR="$DATA/vendor" MODELS="$DATA/models" BIN="$HOME/.local/bin"
PY="$REPO/.venv/bin/python"
say() { printf '\n== %s\n' "$*"; }
need() { command -v "$1" > /dev/null || { echo "install.sh needs $1: $2" >&2; exit 1; }; }
case "$(uname -m)" in aarch64) FFARCH=linuxarm64;; x86_64) FFARCH=linux64;; *) echo "unsupported machine: $(uname -m)" >&2; exit 1;; esac
need uv "https://docs.astral.sh/uv/"; need curl "your package manager"; need make "your package manager"; need c++ "your package manager"
NVCC=$(command -v nvcc || ls /opt/cuda/bin/nvcc /usr/local/cuda/bin/nvcc 2>/dev/null | head -1 || true)
[ -n "$NVCC" ] || { echo "install.sh needs the CUDA toolkit (nvcc) to build dlib for the GPU" >&2; exit 1; }
mkdir -p "$VENDOR" "$BIN"

say "Python packages"
[ -x "$PY" ] || uv venv -q -p 3.12 "$REPO/.venv"
uv pip install -q --python "$PY" --extra-index-url https://download.pytorch.org/whl/cu132 --index-strategy unsafe-best-match \
  -r "$REPO/setup/requirements.txt"

say "dlib with CUDA"
if ! "$PY" -c 'import dlib, sys; sys.exit(not dlib.DLIB_USE_CUDA)' 2> /dev/null; then
  D="$VENDOR/dlib-src"; mkdir -p "$D"
  [ -d "$D/dlib-20.0.1" ] || curl -fsSL https://files.pythonhosted.org/packages/source/d/dlib/dlib-20.0.1.tar.gz | tar xz -C "$D"
  # dlib's setup.py hands cmake only DLIB_ settings; cuDNN's place (from NVIDIA's wheel in .venv) must reach it too.
  sed -i 's/if key.startswith("DLIB_"):/if key.startswith(("DLIB_", "CUDNN_", "CMAKE_CUDA_")):/' "$D/dlib-20.0.1/setup.py"
  CUDNN="$("$PY" -c 'import nvidia.cudnn; print(list(nvidia.cudnn.__path__)[0])')"
  [ -x "$D/env/bin/python" ] || uv venv -q -p 3.12 "$D/env"
  uv pip install -q --python "$D/env/bin/python" setuptools wheel cmake packaging
  (cd "$D/dlib-20.0.1" && rm -rf build dist && PATH="$(dirname "$NVCC"):$PATH" DLIB_USE_CUDA=1 \
    CUDNN_INCLUDE_PATH="$CUDNN/include" CUDNN_LIBRARY_PATH="$CUDNN/lib/libcudnn.so.9" CMAKE_CUDA_ARCHITECTURES=native \
    "$D/env/bin/python" setup.py bdist_wheel > "$D/build.log" 2>&1) || { echo "dlib build failed: see $D/build.log" >&2; exit 1; }
  uv pip install -q --python "$PY" --reinstall "$D"/dlib-20.0.1/dist/dlib-*.whl
fi
"$PY" -c 'import dlib; print("dlib", dlib.__version__, "CUDA devices:", dlib.cuda.get_num_devices())'

say "ffmpeg 8.1 (ffmpeg-gpu)"
F="$VENDOR/ffmpeg-8.1"
if [ ! -x "$F/bin/ffmpeg" ]; then
  mkdir -p "$F" && curl -fsSL "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-n8.1-latest-$FFARCH-gpl-8.1.tar.xz" \
    | tar xJ -C "$F" --strip-components=1
fi
rm -f "$BIN/ffmpeg-gpu" && sed "s|@FFMPEG@|$F/bin/ffmpeg|" "$REPO/bin/ffmpeg-gpu" > "$BIN/ffmpeg-gpu" && chmod +x "$BIN/ffmpeg-gpu"
for t in ffmpeg ffprobe; do command -v "$t" > /dev/null || ln -sf "$F/bin/$t" "$BIN/$t"; done
"$F/bin/ffmpeg" -hide_banner -version | head -1

say "LibRaw 0.22.3"
if [ ! -x "$VENDOR/libraw/bin/dcraw_emu" ]; then
  L="$VENDOR/libraw-src"; mkdir -p "$L"
  [ -d "$L/LibRaw-0.22.3" ] || curl -fsSL https://www.libraw.org/data/LibRaw-0.22.3.tar.gz | tar xz -C "$L"
  # Packaged builds refuse a RAW file over 2 GB, about 11 seconds of 8K: raise the cap to 1 TB.
  (cd "$L/LibRaw-0.22.3" && ./configure -q --prefix="$VENDOR/libraw" \
    CPPFLAGS="-DLIBRAW_MAX_NONDNG_RAW_FILE_SIZE=1099511627776LL -DLIBRAW_MAX_CR3_RAW_FILE_SIZE=1099511627776LL" \
    && make -s -j"$(nproc)" && make -s install) > "$L/build.log" 2>&1 || { echo "LibRaw build failed: see $L/build.log" >&2; exit 1; }
fi
echo "LibRaw in $VENDOR/libraw"

say "Models"
# The models folder is read-only once filled, so nothing changes a model a sidecar was made with (footage/models.py).
mkdir -p "$MODELS"; chmod u+w "$MODELS"
grep -v '^#' "$REPO/setup/models.txt" | while read -r path sum url; do
  f="$MODELS/$path"
  [ -f "$f" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" = "$sum" ] && continue
  echo "  $path"
  mkdir -p "$(dirname "$f")"; chmod -R u+w "$(dirname "$f")"
  case "$url" in *.bz2) curl -fsSL "$url" | bunzip2 > "$f.part";; *) curl -fsSL -o "$f.part" "$url";; esac
  [ "$(sha256sum "$f.part" | cut -d' ' -f1)" = "$sum" ] || { echo "$path: download does not match its sha256" >&2; rm -f "$f.part"; exit 1; }
  mv "$f.part" "$f"
done
T="$MODELS/titanet-large-nvidia"
if [ ! -f "$T/titanet_large.onnx" ]; then
  # NVIDIA's own release, converted with NVIDIA NeMo in a throwaway environment with the network off. NeMo pulls in
  # kaldialign (from k2-fsa), which the export never uses: it is removed and stood in for.
  echo "  titanet-large-nvidia (exported with NeMo; this takes a while)"
  W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
  curl -fsSL -o "$W/titanet_large.nemo" \
    https://huggingface.co/nvidia/speakerverification_en_titanet_large/resolve/0dc382f40121a5fbd34db10a2bb04d826c2be6a8/speakerverification_en_titanet_large.nemo
  uv venv -q -p 3.12 "$W/env"
  uv pip install -q --python "$W/env/bin/python" --extra-index-url https://download.pytorch.org/whl/cpu --index-strategy unsafe-best-match \
    torch==2.15.0 "nemo_toolkit[asr]==3.0.0" onnx
  uv pip uninstall -q --python "$W/env/bin/python" kaldialign
  printf 'def _absent(*a, **k):\n    raise RuntimeError("kaldialign is not installed")\n\n\ndef __getattr__(name):\n    return _absent\n' \
    > "$("$W/env/bin/python" -c 'import site; print(site.getsitepackages()[0])')/kaldialign.py"
  OFF="unshare -rn"; $OFF true 2> /dev/null || OFF="env HF_HUB_OFFLINE=1"  # no network, or at least no hub
  mkdir -p "$W/out" && (cd "$W" && $OFF env/bin/python "$REPO/setup/titanet.py" titanet_large.nemo out > export.log 2>&1) \
    || { cat "$W/export.log" >&2; exit 1; }
  mkdir -p "$T" && cp "$W"/out/* "$T/"
fi
chmod -R a-w "$MODELS"
du -sh "$MODELS"

say "Commands, memory limit and skills"
for c in footage heavy; do sed "s|@REPO@|$REPO|" "$REPO/bin/$c" > "$BIN/$c" && chmod +x "$BIN/$c"; done
mkdir -p "$HOME/.config/systemd/user" && cp "$REPO"/setup/*.slice "$HOME/.config/systemd/user/" && systemctl --user daemon-reload
for agent in "$HOME/.claude" "$HOME/.codex"; do
  [ -d "$agent" ] || continue
  mkdir -p "$agent/skills"
  for s in "$REPO"/skills/*/; do
    s="${s%/}"; link="$agent/skills/$(basename "$s")"
    [ -e "$link" ] && [ ! -L "$link" ] && { echo "  $link is a folder of its own: left as it is" >&2; continue; }
    ln -sfn "$s" "$link" && echo "  $link"
  done
done
C="$HOME/.config/azimuth-video/config.json"
[ -f "$C" ] || { mkdir -p "$(dirname "$C")" && cp "$REPO/setup/config.example.json" "$C" && echo "  wrote $C: add a sentence about what you film"; }
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  add $BIN to your PATH";; esac

say "Check"
"$PY" -c 'from footage import models; print("ONNX models run on", models.providers()[0])'
"$PY" -c 'import torch; print("torch CUDA:", torch.cuda.is_available())'
echo "Installed. Copy clips from a card into ~/Videos/Ingest and run: footage"
