"""Run the pinned upstream engine through its supported manager API contract."""
import asyncio
import os
from pathlib import Path
import shutil
import sys

from aiohttp import ClientSession, ClientTimeout
import yaml

from .config import Config


def prepare():
    settings = Config()
    if not (settings.models / "SenseVoiceSmall" / "model.pt").exists():
        raise RuntimeError("SenseVoiceSmall model.pt is missing; configure ESP_MODELS_DIR first")
    if not settings.source.exists():
        raise RuntimeError("Run git submodule update --init --recursive first")
    shutil.copytree(settings.source, settings.runtime, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("models", "data", "tmp", "__pycache__", ".config.yaml"))
    (settings.runtime / "data").mkdir(exist_ok=True)
    manager_url = f"http://127.0.0.1:{settings.port}/xiaozhi"
    runtime_config = {"server": {"ip": settings.host, "port": 8000, "http_port": 8003,
                       "auth_key": settings.secrets["device"], "vision_explain": ""},
                      "manager-api": {"url": manager_url, "secret": settings.secrets["internal"],
                                      "max_retries": 2, "retry_delay": 1},
                      "prompt_template": "agent-base-prompt.txt"}
    (settings.runtime / "data/.config.yaml").write_text(yaml.safe_dump(runtime_config, allow_unicode=True), encoding="utf-8")
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    if hasattr(os, "add_dll_directory"):
        global _dll_directory
        _dll_directory = os.add_dll_directory(str(Path(sys.executable).parent))
    os.chdir(settings.runtime)
    sys.path.insert(0, str(settings.runtime))
    return settings


async def run(settings, load_config, WebSocketServer, AuthenticationError):
    manager_url = f"http://127.0.0.1:{settings.port}/xiaozhi"
    config = await load_config()
    headers = {"Authorization": "Bearer " + settings.secrets["internal"]}
    async with ClientSession(headers=headers, timeout=ClientTimeout(total=5)) as client:
        class ManagedServer(WebSocketServer):
            def __init__(self, config):
                self.active = {}
                super().__init__(config)

            async def _handle_auth(self, websocket):
                await super()._handle_auth(websocket)
                device_headers = websocket.request.headers
                payload = {"macAddress": device_headers.get("device-id"), "clientId": device_headers.get("client-id")}
                async with client.post(manager_url + "/device/allow", json=payload) as response:
                    result = await response.json()
                    if response.status != 200 or result.get("code") != 0:
                        raise AuthenticationError("Device is not enrolled")
                self.active[websocket] = payload["macAddress"]

            async def _handle_connection(self, websocket):
                try:
                    await super()._handle_connection(websocket)
                finally:
                    self.active.pop(websocket, None)

        server = ManagedServer(config)

        async def heartbeat():
            while True:
                try:
                    async with client.post(manager_url + "/runtime", json={"devices": list(set(server.active.values()))}) as response:
                        await response.read()
                except Exception:
                    pass
                await asyncio.sleep(5)

        await asyncio.gather(server.start(), heartbeat())


if __name__ == "__main__":
    try:
        settings = prepare()
        # Upstream logging performs a synchronous configuration load on import.
        # Import before starting our event loop, matching the upstream entry point.
        from config.settings import load_config
        from core.auth import AuthenticationError
        from core.websocket_server import WebSocketServer
        from core.utils.util import check_ffmpeg_installed
        check_ffmpeg_installed()
        asyncio.run(run(settings, load_config, WebSocketServer, AuthenticationError))
    except KeyboardInterrupt:
        pass
