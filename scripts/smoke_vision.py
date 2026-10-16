"""Real public HTTPS + MCP vision token + model test using a synthetic red photo."""
import argparse
import asyncio
import io
import json
from pathlib import Path
import sys
import uuid

from aiohttp import ClientSession, CookieJar, FormData
from PIL import Image
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.config import Config
from server.store import Store


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-stdin", action="store_true")
    args = parser.parse_args()
    settings = Config()
    credentials = json.loads(sys.stdin.read() if args.credentials_stdin else
                             (settings.data / "first-login.txt").read_text(encoding="utf-8"))
    mac = "02:01:" + ":".join(uuid.uuid4().hex[i:i+2] for i in range(0, 8, 2))
    client_id = uuid.uuid4().hex
    store = Store(settings.data / "control.db")
    created = False
    headers = {"Origin": settings.public_url}
    async with ClientSession(cookie_jar=CookieJar(unsafe=True), headers=headers, trust_env=False) as client:
        try:
            base = settings.public_url
            async with client.post(base + "/api/login", json=credentials) as response:
                assert response.status == 200, "Admin login failed"
            async with client.get(base + "/api/agents") as response:
                agent = (await response.json())[0]
            async with client.post(base + "/api/devices", json={"mac": mac, "name": "Synthetic camera test", "agent_id": agent["id"]}) as response:
                assert response.status == 200
                created = True
            async with client.get(base + f"/api/devices/{mac}/connection") as response:
                ota_url = (await response.json())["ota_url"]
            device_headers = {"Device-Id": mac, "Client-Id": client_id}
            async with client.post(ota_url, json={"application": {"version": "2.5.3"}}, headers=device_headers) as response:
                assert response.status == 200
                ws_config = (await response.json())["websocket"]
            async with connect(ws_config["url"], additional_headers={**device_headers,
                               "Authorization": "Bearer " + ws_config["token"]}) as ws:
                await ws.send(json.dumps({"type": "hello", "version": 1, "transport": "websocket", "features": {"mcp": True},
                    "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}))
                vision = None
                while vision is None:
                    obj = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    payload = obj.get("payload", {}) if obj.get("type") == "mcp" else {}
                    if payload.get("method") == "initialize":
                        vision = payload["params"]["capabilities"]["vision"]
                        await ws.send(json.dumps({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": payload["id"],
                            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                            "serverInfo": {"name": "synthetic-camera", "version": "1"}}}}))
                assert vision["url"] == base + "/mcp/vision/explain", "Worker advertises the wrong vision URL"
                print("PASS: enrolled fixture received public vision URL and token via live MCP initialize", flush=True)
                target = vision["url"]
                for bad in (device_headers, {**device_headers, "Client-Id": "web_test_client"},
                            {**device_headers, "Authorization": "Bearer invalid"},
                            {**device_headers, "Client-Id": "spoofed", "Authorization": "Bearer " + vision["token"]}):
                    async with client.post(target, data=b"invalid", headers=bad) as response:
                        assert response.status == 401, "Vision authentication rejection failed"
                print("PASS: public vision rejects missing, invalid, test-bypass and mismatched-client credentials", flush=True)
                image = io.BytesIO()
                Image.new("RGB", (640, 480), (245, 10, 10)).save(image, format="JPEG")
                form = FormData()
                form.add_field("question", "这张图片主要是什么颜色？只回答颜色。")
                form.add_field("file", image.getvalue(), filename="synthetic-red.jpg", content_type="image/jpeg")
                async with client.post(target, data=form, headers={**device_headers,
                                       "Authorization": "Bearer " + vision["token"]}) as response:
                    result = await response.json()
                    assert response.status == 200, f"Vision returned HTTP {response.status}: {result}"
                    assert result.get("success") and "红" in result["response"], f"Unexpected image analysis: {result}"
                    print("PASS: public HTTPS upload reached real image-capable model: " + result["response"], flush=True)
        finally:
            if created:
                store.execute("DELETE FROM messages WHERE device_id=?", (mac,))
                store.execute("DELETE FROM devices WHERE mac=?", (mac,))
            if client.cookie_jar:
                await client.post(settings.public_url + "/api/logout", json={})


if __name__ == "__main__":
    asyncio.run(main())
