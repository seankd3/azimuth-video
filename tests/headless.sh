#!/bin/bash
# tests/headless.sh COMMAND...: run COMMAND as a Wayland client of a headless Weston that draws on the GPU, then stop
# Weston. The app's video and grade need a GPU renderer, and no test opens a window on the desktop. The first run
# unpacks Weston from the distribution's repository into ~/.local/share/azimuth-video/weston, without installing it.
set -u
D=~/.local/share/azimuth-video/weston L=~/.local/share/azimuth-video/weston/usr/lib
if [ ! -x "$D/usr/bin/weston" ]; then
  T=$(mktemp -d); mkdir -p "$D"
  for u in $(pacman -Sp weston colord libgusb 2>/dev/null | grep -E '/(weston|colord|libgusb)-[0-9]'); do
    curl -fsSL "$u" -o "$T/p.pkg" && tar -xf "$T/p.pkg" -C "$D" --exclude='.[A-Z]*'
  done
  rm -rf "$T"
fi
MAP=$(for m in "$L"/libweston-*/*.so "$L"/weston/*.so; do printf '%s=%s;' "$(basename "$m")" "$m"; done)
SOCK=av-headless-$$
env -u WAYLAND_DISPLAY -u DISPLAY LD_LIBRARY_PATH="$L:$L/weston" WESTON_MODULE_MAP="$MAP" "$D/usr/bin/weston" \
  --backend=headless --renderer=gl --shell=kiosk --socket=$SOCK --width=1600 --height=1000 --no-config \
  > "${XDG_RUNTIME_DIR:-/tmp}/$SOCK.log" 2>&1 &
W=$!
trap 'kill $W 2>/dev/null; wait $W 2>/dev/null; rm -f "${XDG_RUNTIME_DIR:-/tmp}/$SOCK.log"' EXIT
for _ in $(seq 100); do [ -S "$XDG_RUNTIME_DIR/$SOCK" ] && break; read -rt 0.05 <> <(:) || true; done
[ -S "$XDG_RUNTIME_DIR/$SOCK" ] || { echo "weston did not start: $(tail -3 "${XDG_RUNTIME_DIR:-/tmp}/$SOCK.log")" >&2; exit 1; }
AZIMUTH_HEADLESS=$SOCK WAYLAND_DISPLAY=$SOCK QT_QPA_PLATFORM=wayland QT_LOGGING_RULES="qt.multimedia*=false" "$@"
