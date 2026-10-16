import copy
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
VOICES = {"zh-CN-XiaoxiaoNeural": "晓晓 · 温柔女声", "zh-CN-YunxiNeural": "云希 · 自然男声",
          "zh-CN-XiaoyiNeural": "晓伊 · 轻快女声", "zh-CN-YunjianNeural": "云健 · 沉稳男声"}


def http_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("请输入不带账号、查询参数或片段的 HTTP / HTTPS 地址")
    return value.rstrip("/")


class Config:
    def __init__(self, data_dir=None):
        self.data = Path(data_dir or os.environ.get("ESP_DATA_DIR", ROOT / "data")).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        self.host = os.environ.get("ESP_BIND_HOST", "127.0.0.1")
        self.port = int(os.environ.get("ESP_PORT", "8002"))
        self.public_url = http_url(os.environ.get("ESP_PUBLIC_URL", f"http://127.0.0.1:{self.port}"))
        self.ws_url = os.environ.get("ESP_WS_URL", "ws://127.0.0.1:8000/xiaozhi/v1/")
        if urlsplit(self.ws_url).scheme not in ("ws", "wss"):
            raise ValueError("ESP_WS_URL 必须使用 ws:// 或 wss://")
        self.runtime = ROOT / ".runtime" / "voice"
        self.source = ROOT / "vendor" / "xiaozhi" / "main" / "xiaozhi-server"
        self.models = Path(os.environ.get("ESP_MODELS_DIR", self.data / "models")).resolve()
        self.asr_backend = os.environ.get("ESP_ASR_BACKEND", "funasr")
        if self.asr_backend not in ("funasr", "sherpa"):
            raise ValueError("ESP_ASR_BACKEND must be funasr or sherpa")
        self.cookie_secure = self.public_url.startswith("https://")
        path = self.data / "secrets.json"
        if not path.exists():
            # Exclusive create prevents concurrent initializers from rotating keys.
            try:
                with path.open("x", encoding="utf-8") as stream:
                    json.dump({"internal": secrets.token_urlsafe(48), "device": secrets.token_urlsafe(48)}, stream)
                if os.name != "nt":
                    path.chmod(0o600)
            except FileExistsError:
                pass
        self.secrets = json.loads(path.read_text(encoding="utf-8"))

    def agent_config(self, agent, model):
        return {"selected_module": {"LLM": "ManagedLLM", "TTS": "ManagedTTS", "Memory": "nomem", "Intent": "nointent"},
                "LLM": {"ManagedLLM": {"type": "openai", "base_url": model["base_url"],
                    "model_name": model["model"], "api_key": model["api_key"] or "ollama",
                    "temperature": model["temperature"], "max_tokens": model["max_tokens"], "timeout": 60}},
                "TTS": {"ManagedTTS": {"type": "edge", "voice": agent["voice"], "rate": str(agent["rate"]),
                    "volume": "0", "pitch": "0", "output_dir": "tmp/"}},
                "Memory": {"nomem": {"type": "nomem"}}, "Intent": {"nointent": {"type": "nointent"}},
                "prompt": agent["prompt"], "chat_history_conf": 1, "device_max_output_size": 0}

    def engine_config(self, agent, model):
        config = yaml.safe_load((self.source / "config.yaml").read_text(encoding="utf-8"))
        private = self.agent_config(agent, model)
        config.update({key: value for key, value in private.items() if key != "selected_module"})
        asr = "SherpaASR" if self.asr_backend == "sherpa" else "FunASR"
        config["selected_module"] = {"VAD": "SileroVAD", "ASR": asr, **private["selected_module"]}
        if self.asr_backend == "sherpa":
            config["ASR"][asr]["model_dir"] = str(self.models / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
        else:
            config["ASR"][asr].update({"model_dir": str(self.models / "SenseVoiceSmall"), "language": "zh"})
        config["VAD"]["SileroVAD"]["model_dir"] = str(self.models / "snakers4_silero-vad")
        config["server"] = {"ip": self.host, "port": 8000, "http_port": 8003,
                            "auth_key": self.secrets["device"], "auth": {"enabled": True}}
        config["log"]["log_dir"] = "tmp"
        config["log"]["log_level"] = "INFO"
        config["delete_audio"] = True
        config["close_connection_no_voice_time"] = 120
        config["enable_greeting"] = False
        config["enable_stop_tts_notify"] = False
        return copy.deepcopy(config)
