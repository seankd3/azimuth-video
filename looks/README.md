# Looks

Film-print LUTs baked with [spektrafilm](https://github.com/andreavolpato/spektrafilm) 0.3.4. Film modeling powered by `spektrafilm`.
The LUTs are licensed CC BY-SA 4.0 under the terms in `SPEKTRAFILM_LICENSE.txt`, which allow commercial use, free sharing and no resale.

- `vision3-250d_2393.cube`: Kodak Vision3 250D negative printed on Kodak 2393. This is the default look.
- `vision3-250d_2383.cube`: the same negative printed on Kodak 2383, the classic, warmer and softer print.

Both take ACEScct (AP1) and output Rec.709 (BT.1886), and both are 65³. To rebuild them, run
`spektrafilm-lut build --film kodak_vision3_250d --print kodak_2383 --print kodak_2393 --input acescct --output rec709 --resolution 65`.
