"""Bake natural.cube: ACEScct (AP1) in, Rec.709 (BT.1886) out, with no film in between.

Scene light goes to display light through the Khronos PBR Neutral tone mapper: linear through the mid-tones, so colours
are what the camera saw, with a short toe and a smooth shoulder that compresses only the top of the range, desaturating
as it does so bright colours roll off to white instead of clipping to a different hue. In deep shadow colour fades
toward grey, as it does for the eye at night, so a dark lot under green street lights reads dark, not green.

python looks/bake_natural.py   (writes looks/natural.cube, 65^3)
"""
from pathlib import Path

import colour
import numpy as np

N = 65
START = 0.8 - 0.04  # where the shoulder starts, in display light
DESATURATION = 0.15
NIGHT = (0.0015, 0.03, 0.35)  # scene light (18% grey = 0.18) where colour starts to fade, where it is full, least kept


def pbr_neutral(rgb: np.ndarray) -> np.ndarray:
    x = rgb.min(axis=-1, keepdims=True)
    rgb = rgb - np.where(x < 0.08, x - 6.25 * x * x, 0.04)
    peak = rgb.max(axis=-1, keepdims=True)
    d = 1 - START
    new = 1 - d * d / (peak + d - START)
    squeezed = rgb * new / np.maximum(peak, 1e-9)
    g = 1 - 1 / (DESATURATION * (peak - new) + 1)
    return np.where(peak < START, rgb, squeezed * (1 - g) + new * g)


grid = np.linspace(0, 1, N)
b, g, r = np.meshgrid(grid, grid, grid, indexing="ij")  # .cube order: red changes fastest
cct = np.stack([r, g, b], axis=-1).reshape(-1, 3)
ap1 = colour.models.log_decoding_ACEScct(cct)
lin = colour.RGB_to_RGB(ap1, colour.RGB_COLOURSPACES["ACEScg"], colour.RGB_COLOURSPACES["ITU-R BT.709"],
                        chromatic_adaptation_transform="Bradford")
lin = np.maximum(lin, 0)
y = lin @ np.array([0.2126, 0.7152, 0.0722])
t = np.clip((y - NIGHT[0]) / (NIGHT[1] - NIGHT[0]), 0, 1)
keep = NIGHT[2] + (1 - NIGHT[2]) * t * t * (3 - 2 * t)
display = pbr_neutral(y[:, None] + (lin - y[:, None]) * keep[:, None])
out = Path(__file__).with_name("natural.cube")
with open(out, "w") as f:
    f.write(f'TITLE "natural"\nLUT_3D_SIZE {N}\n')
    np.savetxt(f, np.clip(display, 0, 1) ** (1 / 2.4), fmt="%.6f")
print(out)
