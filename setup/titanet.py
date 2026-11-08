"""TitaNet-large to ONNX, with NeMo's own mel filters and window, which footage/transcribe/hear.py computes its input
with. install.sh runs this in a throwaway NeMo environment with the network off.

python titanet.py MODEL.nemo OUT_DIR
"""
import sys

import numpy as np
from nemo.collections.asr.models import EncDecSpeakerLabelModel

nemo, out = sys.argv[1:3]
m = EncDecSpeakerLabelModel.restore_from(nemo, map_location="cpu").eval()
m.export(f"{out}/titanet_large.onnx")
f = m.preprocessor.featurizer
np.save(f"{out}/mel_filters.npy", f.fb.squeeze(0).numpy().astype(np.float32))
np.save(f"{out}/window.npy", f.window.numpy().astype(np.float32))
