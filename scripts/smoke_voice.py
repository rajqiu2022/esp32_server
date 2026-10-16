"""Real synthetic-speech round trip; uses a temporary virtual device, never a physical board."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
if hasattr(os, "add_dll_directory"):
    dll_directory = os.add_dll_directory(str(Path(sys.executable).parent))

from aiohttp import ClientSession, CookieJar
import edge_tts
import opuslib_next
from pydub import AudioSegment
from websockets.asyncio.client import connect

from server.config import Config
from server.store import Store

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--audio", type=Path)
args = parser.parse_args()


async def main():
    settings = Config()
    credentials = json.loads((settings.data / "first-login.txt").read_text(encoding="utf-8"))
    mac = "02:00:" + ":".join(uuid.uuid4().hex[i:i+2] for i in range(0, 8, 2))
    client_id = uuid.uuid4().hex
    store = Store(settings.data / "control.db")
    created = False
    try:
        async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as http:
            async with http.post(settings.public_url + "/api/login", json=credentials) as response:
                assert response.status == 200, "Admin login failed"
            async with http.get(settings.public_url + "/api/agents") as response:
                agent = (await response.json())[0]
            async with http.post(settings.public_url + "/api/devices", json={"name": "Temporary automated voice test", "mac": mac, "agent_id": agent["id"]}) as response:
                assert response.status == 200, "Virtual-device creation failed"
                created = True
            async with http.get(settings.public_url + "/api/devices/" + mac + "/connection") as response:
                ota_url = (await response.json())["ota_url"]
            headers = {"Device-Id": mac, "Client-Id": client_id}
            async with http.post(ota_url, headers=headers, json={"application": {"version": "2.5.3"}}) as response:
                assert response.status == 200
                connection = (await response.json())["websocket"]
            headers["Authorization"] = "Bearer invalid-token"
            async with connect(connection["url"], additional_headers=headers) as ws:
                denied = await asyncio.wait_for(ws.recv(), 10)
                assert "认证失败" in denied, "Unauthenticated device was accepted"
            headers["Authorization"] = "Bearer " + connection["token"]
            if args.audio:
                audio_path = args.audio
            else:
                audio_path = settings.data / "smoke-input.mp3"
                await edge_tts.Communicate("你好，请用一句简短的话介绍你自己。", "zh-CN-XiaoxiaoNeural").save(str(audio_path))
            async with connect(connection["url"], additional_headers=headers) as ws:
                await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket", "features": {"mcp": False},
                    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
                hello = json.loads(await asyncio.wait_for(ws.recv(), 30))
                assert hello.get("type") == "hello"
                print("PASS: enrollment, invalid-token rejection, authenticated WebSocket hello", flush=True)
                await asyncio.sleep(2)
                audio = AudioSegment.from_file(audio_path).set_channels(1).set_frame_rate(16000).set_sample_width(2)
                encoder = opuslib_next.Encoder(16000, 1, opuslib_next.APPLICATION_AUDIO)
                await ws.send(json.dumps({"type": "listen", "state": "start", "mode": "manual"}))
                for offset in range(0, len(audio.raw_data), 1920):
                    frame = audio.raw_data[offset:offset + 1920].ljust(1920, b"\0")
                    await ws.send(encoder.encode(frame, 960))
                    await asyncio.sleep(.06)
                await ws.send(json.dumps({"type": "listen", "state": "stop"}))
                packets, messages = [], []
                while True:
                    message = await asyncio.wait_for(ws.recv(), 90)
                    if isinstance(message, bytes):
                        packets.append(message)
                        continue
                    obj = json.loads(message)
                    messages.append(obj)
                    if obj.get("type") == "tts" and obj.get("state") == "stop":
                        break
                assert any(m.get("type") == "stt" and m.get("text") for m in messages), "No ASR result"
                assert packets, "No synthesized audio received"
                sample_rate = hello.get("audio_params", {}).get("sample_rate", 16000)
                decoder = opuslib_next.Decoder(sample_rate, 1)
                with wave.open(str(settings.data / "smoke-reply.wav"), "wb") as output:
                    output.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                    for packet in packets:
                        output.writeframes(decoder.decode(packet, 5760))
                print(f"PASS: real ASR -> LLM -> TTS -> {len(packets)} Opus packets -> decoded WAV", flush=True)
                for _ in range(30):
                    rows = store.all("SELECT role,content FROM messages WHERE device_id=?", (mac,))
                    if {row["role"] for row in rows} >= {"user", "assistant"}:
                        print("PASS: both sides of voice conversation persisted in control-plane history", flush=True)
                        break
                    await asyncio.sleep(.5)
                else:
                    raise AssertionError("Voice history did not reach the control plane")
    finally:
        if created:
            # Remove only this run's random virtual-device fixture and its messages.
            with store.connect() as db:
                db.execute("DELETE FROM messages WHERE device_id=?", (mac,))
                db.execute("DELETE FROM devices WHERE mac=?", (mac,))


asyncio.run(main())
