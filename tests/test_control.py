import json
from pathlib import Path
import tempfile
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer

from server.app import CONTROLLER, create_app
from server.config import Config


class ControlHarness(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Config(self.temp.name)
        self.app = create_app(self.config)
        self.controller = self.app[CONTROLLER]
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def login(self):
        response = await self.client.post("/api/setup", json={"username": "tester", "password": "local-test-password-123"})
        self.assertEqual(response.status, 200)
        return self.controller.store.one("SELECT * FROM agents")

    async def add_device(self):
        agent = await self.login()
        response = await self.client.post("/api/devices", json={"name": "Test board", "mac": "aa:bb:cc:dd:ee:ff", "agent_id": agent["id"]})
        self.assertEqual(response.status, 200)
        response = await self.client.get("/api/devices/aa:bb:cc:dd:ee:ff/connection")
        return agent, await response.json()

    async def internal(self, path, data=None):
        return await self.client.post("/xiaozhi/" + path, json=data or {},
            headers={"Authorization": "Bearer " + self.config.secrets["internal"]})

class ControlTests(ControlHarness):
    async def test_setup_sessions_and_access_control(self):
        self.assertEqual((await self.client.get("/api/overview")).status, 401)
        await self.login()
        self.assertEqual((await self.client.get("/api/overview")).status, 200)
        stored = self.controller.store.one("SELECT password FROM users")["password"]
        self.assertNotIn("local-test-password", stored)
        duplicate = await self.client.post("/api/setup", json={"username": "other", "password": "long-enough-password"})
        self.assertEqual(duplicate.status, 409)
        await self.client.post("/api/logout", json={})
        self.assertEqual((await self.client.get("/api/overview")).status, 401)
        invalid = await self.client.post("/api/login", json={"username": "tester", "password": "incorrect-password"})
        self.assertEqual(invalid.status, 401)
        valid = await self.client.post("/api/login", json={"username": "tester", "password": "local-test-password-123"})
        self.assertEqual(valid.status, 200)
        self.assertIn("HttpOnly", valid.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", valid.headers["Set-Cookie"])

    async def test_cross_origin_and_internal_auth_are_rejected(self):
        await self.login()
        self.assertEqual((await self.client.post("/api/logout", json={}, headers={"Origin": "https://other.invalid"})).status, 403)
        self.assertEqual((await self.client.post("/api/logout", data="{}")).status, 415)
        self.assertEqual((await self.client.post("/xiaozhi/config/server-base", json={})).status, 401)
        self.assertEqual((await self.client.get("/api/overview", headers={"Host": "attacker.invalid"})).status, 403)

    async def test_model_keys_never_return_to_browser_and_do_not_follow_url_changes(self):
        await self.login()
        model = {"provider": "openai", "model": "model-a", "base_url": "https://model.example/v1",
                 "api_key": "private-test-secret", "temperature": 0.7, "max_tokens": 512}
        self.assertEqual((await self.client.put("/api/model", json=model)).status, 200)
        for path in ("/api/model", "/api/overview"):
            result = await (await self.client.get(path)).text()
            self.assertNotIn("private-test-secret", result)
            self.assertIn('"has_api_key": true', result)
        model.update(api_key="", base_url="https://another.example/v1")
        self.assertEqual((await self.client.put("/api/model", json=model)).status, 400)
        self.assertEqual(self.controller.store.setting("model")["base_url"], "https://model.example/v1")

    async def test_ota_requires_private_enrollment_url_and_pins_client_identity(self):
        _, connection = await self.add_device()
        path = "/" + connection["ota_url"].split("/", 3)[3]
        headers = {"Device-Id": "aa:bb:cc:dd:ee:ff", "Client-Id": "test-device-uuid"}
        response = await self.client.post(path, json={"application": {"version": "2.5.3"}}, headers=headers)
        result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertTrue(result["websocket"]["token"])
        self.assertEqual(result["firmware"]["url"], "")
        devices = await (await self.client.get("/api/devices")).text()
        self.assertNotIn("enrollment_key", devices)
        self.assertNotIn(connection["ota_url"], devices)
        headers["Client-Id"] = "spoofed-client"
        self.assertEqual((await self.client.post(path, json={}, headers=headers)).status, 403)
        headers["Device-Id"] = "aa:bb:cc:dd:ee:00"
        self.assertEqual((await self.client.post(path, json={}, headers=headers)).status, 403)
        self.assertEqual((await self.client.post("/connect/unknown/ota/", json={})).status, 404)

    async def test_device_config_and_idempotent_history_reporting(self):
        agent, connection = await self.add_device()
        path = "/" + connection["ota_url"].split("/", 3)[3]
        await self.client.post(path, json={}, headers={"Device-Id": "aa:bb:cc:dd:ee:ff", "Client-Id": "uuid"})
        data = {"macAddress": "aa:bb:cc:dd:ee:ff", "clientId": "uuid"}
        cfg = await (await self.internal("config/agent-models", data)).json()
        self.assertEqual(cfg["data"]["prompt"], agent["prompt"])
        self.assertEqual(cfg["data"]["selected_module"]["Intent"], "function_call")
        self.assertEqual(cfg["data"]["Intent"]["function_call"]["functions"], [])
        self.assertEqual(cfg["data"]["TTS"]["ManagedTTS"]["voice"], agent["voice"])
        report = {"macAddress": data["macAddress"], "sessionId": "session-1", "chatType": 1, "content": "你好", "reportTime": 1700000000000}
        for _ in range(2):
            self.assertEqual((await self.internal("agent/chat-history/report", report)).status, 200)
        history = await (await self.client.get("/api/history")).json()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "你好")
        self.assertEqual(history[0]["device_id"], data["macAddress"])

    async def test_stale_heartbeat_does_not_mark_devices_online(self):
        await self.add_device()
        await self.internal("runtime", {"devices": ["aa:bb:cc:dd:ee:ff"]})
        self.assertTrue((await (await self.client.get("/api/devices")).json())[0]["online"])
        self.controller.store.save_setting("runtime", {"time": time.time() - 60, "devices": ["aa:bb:cc:dd:ee:ff"]})
        self.assertFalse((await (await self.client.get("/api/devices")).json())[0]["online"])

    async def test_cloud_worker_receives_quantized_asr_config(self):
        self.config.asr_backend = "sherpa"
        response = await self.internal("config/server-base")
        self.assertEqual(response.status, 200)
        config = (await response.json())["data"]
        name = config["selected_module"]["ASR"]
        self.assertEqual(config["ASR"][name]["type"], "sherpa_onnx_local")
        self.assertTrue(Path(config["ASR"][name]["model_dir"]).is_relative_to(self.config.models))
        self.assertTrue(config["server"]["auth"]["enabled"])

    async def test_chat_preserves_context_and_rejects_cross_agent_sessions(self):
        agent = await self.login()
        seen = []
        async def completion(messages):
            seen.append(messages)
            return "你好，很高兴见到你。"
        self.controller.completion = completion
        first = await (await self.client.post("/api/chat", json={"agent_id": agent["id"], "text": "你好"})).json()
        self.assertEqual(len(seen[0]), 2)
        response = await self.client.post("/api/chat", json={"agent_id": agent["id"], "text": "继续聊", "session_id": first["session_id"]})
        self.assertEqual(response.status, 200)
        self.assertEqual(len(seen[1]), 4)
        self.assertEqual(self.controller.store.one("SELECT count(*) AS n FROM messages")["n"], 4)
        other = await (await self.client.post("/api/agents", json={"name": "Other", "prompt": "Hello", "voice": "zh-CN-YunxiNeural", "rate": 0})).json()
        response = await self.client.post("/api/chat", json={"agent_id": other["id"], "text": "你好", "session_id": first["session_id"]})
        self.assertEqual(response.status, 409)


if __name__ == "__main__":
    unittest.main()
