#!/usr/bin/env bash
# Filing acceptance on synthetic clips in a sandbox. It needs ffmpeg, and never touches a real Ingest or Library.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
S="$(mktemp -d)"; SRC=$S/src; mkdir -p "$SRC" "$S/in" "$S/lib"
export AZIMUTH_VIDEO_CONFIG=$S/config.json
echo '{"timezone": "America/New_York"}' > "$AZIMUTH_VIDEO_CONFIG"
trap 'chmod -R u+rw "$S" 2>/dev/null; rm -rf "$S"' EXIT

# Ten distinct 2-second clips laid out like camera files (index before media), each with a capture time.
clip() {  # name, capture time (UTC), hue
  ffmpeg -v error -f lavfi -i "testsrc2=size=320x180:rate=30000/1001:duration=2" -f lavfi -i "sine=f=$((200 + $3)):d=2" \
    -vf "hue=h=$3" -c:v libx264 -preset ultrafast -c:a aac -metadata creation_time="$2" -movflags +faststart "$SRC/$1.MP4"
}
clip A 2026-10-26T20:47:00Z 0;   clip B 2026-10-27T17:00:00Z 20;  clip C 2026-10-27T17:05:00Z 40
clip D 2026-10-27T17:10:00Z 60;  clip E 2026-10-27T17:15:00Z 80;  clip F 2026-10-27T17:20:00Z 100
clip G 2026-10-27T17:25:00Z 120; clip H 2026-10-27T17:30:00Z 140; clip I 2026-10-27T17:35:00Z 160
clip J 2026-10-27T17:40:00Z 180
src() { echo "$SRC/$1.MP4"; }
same() { [ -n "$1" ] && [ "$1" = "$2" ]; }
run() { (cd "$HERE" && "$PY" -c "
from pathlib import Path; from footage import library
r = []; library.file_inbox(Path('$S/in'), Path('$S/lib'), r)
[print('   ', *x) for x in r]") 2>&1; }
fail=0; check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; fail=1; fi; }
moov_end() { "$PY" -c "
import sys; f=open(sys.argv[1],'rb'); pos=0
while True:
    f.seek(pos); h=f.read(8); n=int.from_bytes(h[:4],'big'); pos+=n
    if h[4:8]==b'moov': print(pos); break" "$1"; }
day26=$S/lib/2026-10-26; day27=$S/lib/2026-10-27; C=$S/in/.claimed
for c in A B C; do ln "$(src $c)" "$S/in/$c.MP4"; done

echo "1. first run files three clips into their shooting days"; run
check "three clips filed with sidecars, inbox empty" '[ $(ls $S/lib/*/*.MP4 | wc -l) = 3 ] && [ $(ls $S/lib/*/*.MP4.json | wc -l) = 3 ] && [ -z "$(ls $S/in)" ] && [ -z "$(ls -A $C)" ]'
check "A (20:47 UTC Oct 26) is in 2026-10-26" '[ -f $day26/A.MP4 ]'
check "filed bytes are the source bytes (same inode)" 'same "$(stat -c %i $day27/B.MP4)" "$(stat -c %i $(src B))"'
check "sidecar hash matches media" 'same "$("$PY" -c "import json;print(json.load(open(\"$day27/B.MP4.json\"))[\"facts\"][\"sha256\"])")" "$(sha256sum $(src B) | cut -c1-64)"'

echo "2. second run changes nothing"; before=$(find $S/in $S/lib -printf '%p %i %s\n' | sort | md5sum); run
check "no change" '[ "$before" = "$(find $S/in $S/lib -printf "%p %i %s\n" | sort | md5sum)" ]'

echo "3. duplicates stay in the inbox: a byte-identical copy, and a second hard link to a filed clip"
cp --reflink=auto $(src C) $S/in/COPYC.MP4; ln $(src B) $S/in/LINKB.MP4; run
check "both duplicates stay, nothing new filed" '[ -f $S/in/COPYC.MP4 ] && [ -f $S/in/LINKB.MP4 ] && [ $(ls $S/lib/*/*.MP4 | wc -l) = 3 ]'
rm $S/in/COPYC.MP4 $S/in/LINKB.MP4

echo "4. interrupted runs are finished from .claimed: one linked without a sidecar, one claimed but not linked"
ln $(src D) $C/D.MP4; ln $(src D) $day27/D.MP4; ln $(src E) $C/E.MP4; run
check "both finished, .claimed empty" '[ -f $day27/D.MP4.json ] && [ -f $day27/E.MP4.json ] && [ -z "$(ls $C)" ]'

echo "5. half-copied files wait: cut mid-media, and cut exactly after the index"
head -c $(( $(stat -c %s $(src F)) / 2 )) $(src F) > $S/in/F.MP4; head -c $(moov_end $(src G)) $(src G) > $S/in/G.MP4; run
check "neither truncated file filed" '[ -f $S/in/F.MP4 ] && [ -f $S/in/G.MP4 ] && [ -z "$(ls $S/lib/*/F* $S/lib/*/G* 2>/dev/null)" ]'
rm $S/in/F.MP4 $S/in/G.MP4

echo "6. a file another program still holds open waits"
ln $(src H) $S/in/H.MP4; exec 3<$S/in/H.MP4; run; exec 3<&-
check "open file not filed" '[ -f $S/in/H.MP4 ]'; run
check "filed once closed" '[ ! -e $S/in/H.MP4 ] && [ -f $day27/H.MP4.json ]'

echo "7. a different clip arriving under a taken name gets -2 and keeps its original name"
ln $(src I) $S/in/B.MP4; run
check "B-2 filed, first untouched" '[ -f $day27/B-2.MP4 ] && same "$(stat -c %i $day27/B.MP4)" "$(stat -c %i $(src B))" && grep -q "\"original_name\": \"B.MP4\"" $day27/B-2.MP4.json'

echo "8. UTC midnight belongs to the previous local day"
check "02:00Z Oct 27 -> 2026-10-26" '[ "$(cd "$HERE" && "$PY" -c "from footage.library import day_of; print(day_of(\"2026-10-27T02:00:00+00:00\"))")" = 2026-10-26 ]'

echo "9. two runs at once: the second refuses"
(exec 4>$S/lib/.lock; flock 4; (cd "$HERE" && "$PY" -m footage --ingest $S/in --library $S/lib) > $S/second.txt 2>&1)
check "second run refused" 'grep -q "Another footage run" $S/second.txt'

echo "10. one unusable file and one broken sidecar do not stop the rest"
ffmpeg -v error -f lavfi -i sine=d=2 -c:a aac $S/in/AUDIO.mp4; echo '{broken' > $day26/A.MP4.json; ln $(src J) $S/in/J.MP4; run
check "audio-only reported and left, broken sidecar reported, good clip still filed" '[ -f $S/in/AUDIO.mp4 ] && [ -f $day27/J.MP4.json ]'

echo "11. misshapen and unreadable sidecars are reported, filing and describing carry on"
"$PY" -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d['description']=['hand edit']; json.dump(d,open(p,'w'))" $day27/D.MP4.json
echo '{"version":1}' > $day27/B.MP4.json; echo '[]' > $day27/C.MP4.json; chmod 000 $day27/E.MP4.json
rm $day27/J.MP4 $day27/J.MP4.json; ln $(src J) $S/in/J.MP4; run | tee $S/filing.txt
(cd "$HERE" && "$PY" -c "
from pathlib import Path; import footage.__main__ as m
r = []; m.fill(Path('$S/lib'), m.PASSES[0], r)" > $S/describe.txt 2>&1); chmod 644 $day27/E.MP4.json
check "J filed despite four bad sidecars" '[ -f $day27/J.MP4.json ]'
check "the bad description is reported, not silently skipped" 'grep -q "D.MP4" $S/filing.txt'

echo "12. white balance: a frame full of one strong colour keeps its grey; with no grey near the camera's balance, it stands"
wb() { (cd "$HERE" && "$PY" -c "
import numpy as np
from footage.measure import neutral
rng = np.random.default_rng(0)
grey = rng.uniform(0.1, 0.6, (5000, 1)) * np.ones(3)                        # a little wall, recorded grey
red = rng.uniform(0.1, 0.6, (95000, 1)) * np.array([1.0, 0.22, 0.12])      # a red machine filling the frame
wood = rng.uniform(0.1, 0.6, (100000, 1)) * np.array([1.0, 0.62, 0.32])    # a close-up of one colour, no grey
cast = 2.0 ** (2.35 * np.array([0.5, 0, -0.5]))                              # a tungsten preset in daylight
a = neutral(np.concatenate([grey, red]))
none = lambda n: n['gate'] is None and np.allclose(n['rgb'], 1)
print('ok' if a['gate'] and abs(np.log2(a['rgb'][0] / a['rgb'][2])) < 0.1 and all(map(none, (neutral(wood), neutral(grey * cast), neutral(np.zeros((1000, 3)))))) else 'bad')
"); }
check "colour-dominated stays neutral; no grey near the camera's balance means no estimate" '[ "$(wb)" = ok ]'

echo; if [ $fail = 0 ]; then echo "ACCEPTANCE PASSED"; else echo "ACCEPTANCE FAILED"; fi
exit $fail
