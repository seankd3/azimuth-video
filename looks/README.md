# Looks

Film-print LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) 0.3.4. Film modeling powered by `spektrafilm`.
The LUTs are licensed CC BY-SA 4.0 under the terms in `SPEKTRAFILM_LICENSE.txt`, which allow commercial use, free sharing and no resale.

A look is a `NAME.json` file: the LUT it prints through and how it is printed (exposure, contrast, warmth, black and
white levels, halation, vignette). `footage/grade.py` documents each setting. To make a new look, copy a file and
change its numbers.

- `vision3-250d_2393.cube`: Kodak Vision3 250D negative printed on Kodak 2393 (`cinema`).
- `vision3-250d_2383.cube`: the same negative printed on Kodak 2383, the classic, warmer and softer print (`classic`).
- `vision3-500t_2393.cube`: Kodak Vision3 500T, the tungsten stock CineStill 800T is made from, printed on 2393 (`cinestill-800t`).
- `gold-200_ektacolor-edge.cube`: Kodak Gold 200 printed on Kodak Ektacolor Edge paper (`kodak-gold-200`).
- `portra-400_portra-endura.cube`: Kodak Portra 400 printed on Kodak Portra Endura paper (`portra-400`).
- `fuji-pro-400h_crystal-archive.cube`: Fujifilm Pro 400H printed on Fujifilm Crystal Archive paper (`fuji-pro-400h`).
- `fuji-superia-400_crystal-archive.cube`: Fujifilm Superia X-tra 400 printed on Crystal Archive paper (`fuji-superia-400`).

All take ACEScct (AP1) and output Rec.709 (BT.1886), and all are 65³. To rebuild one, run for example
`spektrafilm-lut build --film kodak_gold_200 --print kodak_ektacolor_edge --input acescct --output rec709 --resolution 65`.
