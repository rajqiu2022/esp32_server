"""Download SenseVoice once and copy the pinned Silero VAD files into the model cache."""
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.config import Config

config = Config()
config.models.mkdir(parents=True, exist_ok=True)
source = config.source / "models/snakers4_silero-vad"
target = config.models / "snakers4_silero-vad"
if source.resolve() != target.resolve():
    shutil.copytree(source, target, dirs_exist_ok=True)
from modelscope import snapshot_download
snapshot_download("iic/SenseVoiceSmall", local_dir=str(config.models / "SenseVoiceSmall"))
print("Models prepared. Set ESP_MODELS_DIR if using a different cache directory.")
