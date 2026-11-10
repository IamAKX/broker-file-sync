"""Downloads the offline speech-recognition model for Ask Fuku's voice mode
into assets/voice_models/<name>, so PyInstaller's `--add-data "assets;assets"`
ships it inside the build and users never need to download it.

Run before PyInstaller (the build scripts do):  python tools/fetch_voice_model.py
Without it the app still works — it downloads the model on first use instead.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.voice_io import BUNDLED_MODELS_DIR, MODEL_NAME  # noqa: E402


def main() -> None:
    from faster_whisper import download_model

    target = os.path.join(BUNDLED_MODELS_DIR, MODEL_NAME)
    if os.path.isfile(os.path.join(target, "model.bin")):
        print(f"Voice model already present: {target}")
        return
    os.makedirs(target, exist_ok=True)
    download_model(MODEL_NAME, output_dir=target)
    print(f"Voice model '{MODEL_NAME}' saved to {target}")


if __name__ == "__main__":
    main()
