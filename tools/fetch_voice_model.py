"""Downloads the offline models for Ask Fuku's voice mode into
assets/voice_models/, so PyInstaller's `--add-data "assets;assets"` ships them
inside the build:

  <MODEL_NAME>      speech recognition (Whisper)          ~145 MB
  <TTS_MODEL_NAME>  the neural voice (Kokoro / Piper)     ~360 MB for Kokoro

Run before PyInstaller (the build scripts do):  python tools/fetch_voice_model.py
Without them the app still works: the Whisper model is downloaded on first use,
and answers are spoken with the operating system's voice instead of the neural one.
"""

import os
import sys
import tarfile
import tempfile
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.voice_io import BUNDLED_MODELS_DIR, MODEL_NAME, TTS_MODEL_NAME  # noqa: E402

_TTS_URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/{name}.tar.bz2"


def fetch_whisper() -> None:
    from faster_whisper import download_model

    target = os.path.join(BUNDLED_MODELS_DIR, MODEL_NAME)
    if os.path.isfile(os.path.join(target, "model.bin")):
        print(f"Speech recognition model already present: {target}")
        return
    os.makedirs(target, exist_ok=True)
    download_model(MODEL_NAME, output_dir=target)
    print(f"Speech recognition model '{MODEL_NAME}' saved to {target}")


def fetch_tts() -> None:
    target = os.path.join(BUNDLED_MODELS_DIR, TTS_MODEL_NAME)
    if os.path.isfile(os.path.join(target, "tokens.txt")):
        print(f"Neural voice already present: {target}")
        return
    os.makedirs(BUNDLED_MODELS_DIR, exist_ok=True)
    url = _TTS_URL.format(name=TTS_MODEL_NAME)
    print(f"Downloading the neural voice from {url} ...")
    with tempfile.NamedTemporaryFile(suffix=".tar.bz2", delete=False) as tmp:
        archive = tmp.name
    try:
        urllib.request.urlretrieve(url, archive)
        with tarfile.open(archive, "r:bz2") as tar:
            tar.extractall(BUNDLED_MODELS_DIR, filter="data")   # archive's top folder is <TTS_MODEL_NAME>/
    finally:
        os.remove(archive)
    if not os.path.isfile(os.path.join(target, "tokens.txt")):
        raise SystemExit(f"The archive did not contain {TTS_MODEL_NAME}/tokens.txt")
    print(f"Neural voice '{TTS_MODEL_NAME}' saved to {target}")


if __name__ == "__main__":
    fetch_whisper()
    fetch_tts()
