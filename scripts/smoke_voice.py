"""Real synthetic-speech round trip; uses a temporary virtual device, never a physical board."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
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
parser.add_argument("--simulate-light", action="store_true", help="Prove live ASR/model/MCP routing against a temporary virtual lamp")
parser.add_argument("--text", default="你好，请用一句简短的话介绍你自己。")
parser.add_argument("--expect-text", help="Require this text in the generated speech transcript")
parser.add_argument("--credentials-stdin", action="store_true", help="Read login JSON from stdin without saving a password file")
parser.add_argument("--local-services", action="store_true", help="Test loopback services inside a cloud container")
parser.add_argument("--speech-only", action="store_true", help="Verify live ASR and independent TTS while the LLM API is unconfigured")
args = parser.parse_args()


async def main():
    settings = Config()
    credentials = json.loads(sys.stdin.read() if args.credentials_stdin else
                             (settings.data / "first-login.txt").read_text(encoding="utf-8"))
    base_url = f"http://127.0.0.1:{settings.port}" if args.local_services else settings.public_url
    host_headers = {"Host": urlsplit(settings.public_url).netloc, "Origin": settings.public_url}
    mac = "02:00:" + ":".join(uuid.uuid4().hex[i:i+2] for i in range(0, 8, 2))
    client_id = uuid.uuid4().hex
    store = Store(settings.data / "control.db")
    created = False
    fixture_task = None
    try:
        async with ClientSession(cookie_jar=CookieJar(unsafe=True, treat_as_secure_origin=[base_url]), headers=host_headers) as http:
            async with http.post(base_url + "/api/login", json=credentials) as response:
                assert response.status == 200, "Admin login failed"
            async with http.get(base_url + "/api/agents") as response:
                agent = (await response.json())[0]
            async with http.post(base_url + "/api/devices", json={"name": "Temporary automated voice test", "mac": mac, "agent_id": agent["id"]}) as response:
                assert response.status == 200, "Virtual-device creation failed"
                created = True
            async with http.get(base_url + "/api/devices/" + mac + "/connection") as response:
                ota_url = (await response.json())["ota_url"]
                if args.local_services:
                    ota_url = base_url + urlsplit(ota_url).path
            headers = {"Device-Id": mac, "Client-Id": client_id}
            async with http.post(ota_url, headers=headers, json={"application": {"version": "2.5.3"}}) as response:
                assert response.status == 200
                connection = (await response.json())["websocket"]
            ws_url = "ws://127.0.0.1:8000/xiaozhi/v1/" if args.local_services else connection["url"]
            headers["Authorization"] = "Bearer invalid-token"
            async with connect(ws_url, additional_headers=headers) as ws:
                denied = await asyncio.wait_for(ws.recv(), 10)
                assert "认证失败" in denied, "Unauthenticated device was accepted"
            headers["Authorization"] = "Bearer " + connection["token"]
            if args.audio:
                audio_path = args.audio
            else:
                audio_path = settings.data / "smoke-input.mp3"
                await edge_tts.Communicate(args.text, "zh-CN-XiaoxiaoNeural").save(str(audio_path))
            async with connect(ws_url, additional_headers=headers) as ws:
                if args.simulate_light:
                    from light_fixture import LightFixture
                    fixture = LightFixture()
                    fixture_task = asyncio.create_task(fixture.read(ws))
                    recv = fixture.recv
                else:
                    recv = ws.recv
                await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket", "features": {"mcp": args.simulate_light},
                    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
                hello = json.loads(await asyncio.wait_for(recv(), 30))
                assert hello.get("type") == "hello"
                print("PASS: enrollment, invalid-token rejection, authenticated WebSocket hello", flush=True)
                if args.simulate_light:
                    await asyncio.wait_for(fixture.ready.wait(), 15)
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
                    message = await asyncio.wait_for(recv(), 90)
                    if isinstance(message, bytes):
                        packets.append(message)
                        continue
                    obj = json.loads(message)
                    messages.append(obj)
                    if args.speech_only and obj.get("type") == "stt" and obj.get("text"):
                        await ws.send(json.dumps({"type": "abort"}))
                        break
                    if obj.get("type") == "tts" and obj.get("state") == "stop":
                        break
                assert any(m.get("type") == "stt" and m.get("text") for m in messages), "No ASR result"
                if args.simulate_light:
                    assert fixture.calls and fixture.on is True, "Model did not execute the lamp-on tool"
                    print("PASS: recognized speech caused an acknowledged device MCP lamp-on call", flush=True)
                if args.speech_only:
                    print("PASS: live cloud worker recognized synthetic speech", flush=True)
                    target = settings.data / "cloud-tts-check.mp3"
                    await edge_tts.Communicate("云端语音合成测试成功。", agent["voice"]).save(str(target))
                    decoded = AudioSegment.from_mp3(target)
                    assert len(decoded) > 100, "No valid synthesized audio"
                    decoded.export(settings.data / "cloud-tts-check.wav", format="wav")
                    print("PASS: independent cloud TTS synthesized and decoded; LLM validation pending API configuration", flush=True)
                    required_roles = {"user"}
                else:
                    assert packets, "No synthesized audio received"
                    if args.expect_text:
                        transcript = "".join(m.get("text", "") for m in messages if m.get("type") == "tts")
                        assert args.expect_text in transcript, f"Expected answer missing: {transcript}"
                        print("PASS: expected answer in generated speech: " + transcript, flush=True)
                    sample_rate = hello.get("audio_params", {}).get("sample_rate", 16000)
                    decoder = opuslib_next.Decoder(sample_rate, 1)
                    with wave.open(str(settings.data / "smoke-reply.wav"), "wb") as output:
                        output.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
                        for packet in packets:
                            output.writeframes(decoder.decode(packet, 5760))
                    print(f"PASS: real ASR -> LLM -> TTS -> {len(packets)} Opus packets -> decoded WAV", flush=True)
                    required_roles = {"user", "assistant"}
                for _ in range(30):
                    rows = store.all("SELECT role,content FROM messages WHERE device_id=?", (mac,))
                    if {row["role"] for row in rows} >= required_roles:
                        print("PASS: expected voice records persisted in control-plane history", flush=True)
                        break
                    await asyncio.sleep(.5)
                else:
                    raise AssertionError("Voice history did not reach the control plane")
    finally:
        if fixture_task:
            fixture_task.cancel()
            await asyncio.gather(fixture_task, return_exceptions=True)
        if created:
            # Remove only this run's random virtual-device fixture and its messages.
            with store.connect() as db:
                db.execute("DELETE FROM messages WHERE device_id=?", (mac,))
                db.execute("DELETE FROM devices WHERE mac=?", (mac,))


asyncio.run(main())
