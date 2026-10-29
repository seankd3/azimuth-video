"""Camera colour science in one place: decoding a clip's code values to scene-linear Rec.709, and display encoding."""
import numpy as np

VERSION = 1  # bump when decoding or display encoding changes, so everything measured from colour is redone
CLIP = 0.985  # code value at which the camera's sensor saturates: anything there is light the camera couldn't hold


def identity(sc: dict) -> dict:
    """Everything a clip's decoded colour depends on: part of the identity of every section read from colour."""
    return {"color": VERSION, "log": sc["assumed"]["log"], "gamut": sc["assumed"]["gamut"]}


def to_linear_709(code: np.ndarray, assumed: dict) -> np.ndarray:
    """Full-range RGB code values (0..1) to scene-linear Rec.709, where 0.18 is mid grey."""
    import colour
    if assumed.get("log") == "Canon Log 3" and assumed.get("gamut") == "Cinema Gamut":
        lin = colour.models.log_decoding_CanonLog3(code, in_normalised_code_value=True, out_reflection=True)
        return colour.RGB_to_RGB(lin, colour.RGB_COLOURSPACES["Cinema Gamut"], colour.RGB_COLOURSPACES["ITU-R BT.709"])
    return colour.models.eotf_BT1886(code)  # anything else is treated as ordinary Rec.709 video


def to_acescct(lin: np.ndarray) -> np.ndarray:
    """Scene-linear Rec.709 to ACEScct (AP1 primaries, log): the grading space the look LUT takes as input."""
    import colour
    ap1 = colour.RGB_to_RGB(lin, colour.RGB_COLOURSPACES["ITU-R BT.709"], colour.RGB_COLOURSPACES["ACEScg"])
    with np.errstate(invalid="ignore", divide="ignore"):  # the unused log branch sees the toe's negatives
        return colour.models.log_encoding_ACEScct(ap1)


def luminance(lin: np.ndarray) -> np.ndarray:
    return lin @ np.array([0.2126, 0.7152, 0.0722])


def tone(lin: np.ndarray) -> np.ndarray:
    """Scene-linear to display Rec.709 (BT.1886 2.4): a filmic curve with a soft shoulder, mid grey near 42%."""
    x = np.clip(lin, 0, None) * 0.6
    d = np.clip((x * (2.51 * x + 0.03)) / (x * (2.43 * x + 0.59) + 0.14), 0, 1)
    return d ** (1 / 2.4)


def display(lin: np.ndarray) -> np.ndarray:
    """Scene-linear to 8-bit display RGB: the one picture recognition models see."""
    return (np.clip(tone(lin), 0, 1) * 255).astype(np.uint8)
