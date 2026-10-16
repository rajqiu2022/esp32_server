import io
from unittest.mock import patch

from aiohttp import FormData
from PIL import Image

from test_control import ControlHarness
from server.vision import MAX_IMAGE


class VisionTests(ControlHarness):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await self.add_device()
        self.mac = "aa:bb:cc:dd:ee:ff"
        self.controller.store.execute("UPDATE devices SET client_id=? WHERE mac=?", ("camera-uuid", self.mac))
        self.headers = {"Device-Id": self.mac, "Client-Id": "camera-uuid",
                        "Authorization": "Bearer " + self.controller.vision.auth.generate_token(self.mac)}
        image = io.BytesIO()
        Image.new("RGB", (640, 480), "red").save(image, format="JPEG")
        self.photo = image.getvalue()
        self.calls = []

        async def completion(messages):
            self.calls.append(messages)
            return "照片中是红色画面。"
        self.controller.completion = completion

    def form(self, photo=None, question="看到了什么？"):
        form = FormData()
        form.add_field("question", question)
        form.add_field("file", self.photo if photo is None else photo, filename="camera.jpg", content_type="image/jpeg")
        return form

    async def post(self, photo=None, headers=None):
        return await self.client.post("/mcp/vision/explain", data=self.form(photo),
                                      headers=self.headers if headers is None else headers)

    async def test_camera_auth_has_no_web_test_bypass_and_pins_both_identities(self):
        for headers in ({}, {"Client-Id": "web_test_client"},
                        {**self.headers, "Authorization": "Bearer invalid"},
                        {**self.headers, "Device-Id": "aa:bb:cc:dd:ee:00"},
                        {**self.headers, "Client-Id": "spoofed"}):
            self.assertEqual((await self.post(headers=headers)).status, 401)
        self.assertEqual((await self.post(headers=self.headers)).status, 200)
        self.assertEqual(len(self.calls), 1)

    async def test_expired_token_is_rejected(self):
        with patch("time.time", return_value=9999999999):
            self.assertEqual((await self.post()).status, 401)
        self.assertEqual(self.calls, [])

    async def test_photo_reaches_model_as_image_and_is_not_persisted(self):
        response = await self.post()
        self.assertEqual(response.status, 200)
        self.assertTrue((await response.json())["success"])
        content = self.calls[0][-1]["content"]
        self.assertEqual(content[0]["text"], "看到了什么？")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,/9j/"))
        self.assertEqual(self.controller.store.one("SELECT count(*) AS n FROM messages")["n"], 0)
        self.assertEqual((await self.post()).status, 429)

    async def test_malformed_oversized_and_chunked_images_are_bounded(self):
        self.assertEqual((await self.post(b"not-a-jpeg")).status, 400)
        self.controller.vision.last_request.clear()
        self.assertEqual((await self.post(b"x" * (MAX_IMAGE + 1))).status, 413)
        self.controller.vision.last_request.clear()
        boundary = b"camera-test"

        async def chunks():
            yield b"--" + boundary + b'\r\nContent-Disposition: form-data; name="file"; filename="c.jpg"\r\n\r\n'
            for _ in range(257):
                yield b"x" * 8192
            yield b"\r\n--" + boundary + b"--\r\n"
        response = await self.client.post("/mcp/vision/explain", data=chunks(), headers={**self.headers,
                          "Content-Type": "multipart/form-data; boundary=camera-test"})
        self.assertEqual(response.status, 413)
        self.assertFalse(self.controller.vision.busy)
        self.assertEqual(self.calls, [])

    async def test_worker_advertises_the_public_vision_endpoint(self):
        result = await (await self.internal("config/server-base")).json()
        self.assertEqual(result["data"]["server"]["vision_explain"],
                         self.config.public_url + "/mcp/vision/explain")
