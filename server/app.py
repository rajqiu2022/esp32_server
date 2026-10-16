import asyncio
from collections import defaultdict, deque
import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from urllib.parse import urlsplit

from aiohttp import ClientSession, ClientTimeout, web

from .config import Config, ROOT, VOICES, http_url
from .security import device_token, password_hash, password_matches, token_hash
from .store import Store


def text(data, key, maximum, minimum=1):
    value = data.get(key, "")
    if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
        raise ValueError(f"{key} 长度应为 {minimum}–{maximum} 个字符")
    return value.strip()


def mac_address(value):
    value = str(value).lower().replace("-", ":")
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", value):
        raise ValueError("请输入完整 MAC 地址，例如 10:20:ba:00:00:01")
    return value


def number(data, key, low, high, integer=False):
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValueError(f"{key} 应在 {low}–{high} 之间")
    if integer and int(value) != value:
        raise ValueError(f"{key} 必须为整数")
    return int(value) if integer else value


class Controller:
    def __init__(self, config):
        self.config = config
        self.store = Store(config.data / "control.db")
        self.failures = defaultdict(deque)
        self.chat_busy = set()

    def user(self, request):
        token = request.cookies.get("esp_session", "")
        return self.store.one("SELECT users.id,users.username FROM sessions JOIN users ON users.id=sessions.user_id "
                              "WHERE sessions.hash=? AND expires>?", (token_hash(token), int(time.time())))

    def ok(self, value=None):
        return web.json_response({"code": 0, "data": value}, dumps=lambda x: json.dumps(x, ensure_ascii=False))

    async def identity(self, request):
        return web.json_response({"needs_setup": not bool(self.store.one("SELECT id FROM users")),
                                  "user": self.user(request), "voices": VOICES})

    async def session(self, request):
        now = time.time()
        attempts = self.failures[request.remote or "local"]
        while attempts and attempts[0] < now - 300:
            attempts.popleft()
        if len(attempts) >= 8:
            raise web.HTTPTooManyRequests(text="尝试过于频繁，请五分钟后重试")
        data = await request.json()
        username = text(data, "username", 64, 3)
        password = data.get("password", "")
        if not isinstance(password, str) or not 12 <= len(password) <= 256:
            raise ValueError("密码长度应为 12–256 个字符")
        if request.path == "/api/setup":
            if self.store.one("SELECT id FROM users"):
                raise web.HTTPConflict(text="管理员已经创建，请登录")
            hashed = await asyncio.to_thread(password_hash, password)
            # The scrypt await permits concurrent requests; recheck under the write transaction.
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if db.execute("SELECT id FROM users").fetchone():
                    raise web.HTTPConflict(text="管理员已经创建，请登录")
                db.execute("INSERT INTO users(username,password) VALUES(?,?)", (username, hashed))
            user = self.store.one("SELECT id,username FROM users WHERE username=?", (username,))
        else:
            user = self.store.one("SELECT * FROM users WHERE username=?", (username,))
            # Equal-cost dummy check for unknown usernames.
            stored = user["password"] if user else "0" * 32 + ":" + "0" * 64
            valid = await asyncio.to_thread(password_matches, password, stored)
            if not user or not valid:
                attempts.append(now)
                raise web.HTTPUnauthorized(text="账号或密码不正确")
        attempts.clear()
        token = secrets.token_urlsafe(40)
        self.store.execute("DELETE FROM sessions WHERE expires<?", (int(now),))
        self.store.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user["id"], int(now) + 86400))
        response = web.json_response({"username": user["username"]})
        response.set_cookie("esp_session", token, httponly=True, secure=self.config.cookie_secure,
                            samesite="Strict", max_age=86400, path="/")
        return response

    async def logout(self, request):
        self.store.execute("DELETE FROM sessions WHERE hash=?", (token_hash(request.cookies.get("esp_session", "")),))
        response = web.json_response({"ok": True})
        response.del_cookie("esp_session", path="/")
        return response

    def devices(self):
        runtime = self.store.setting("runtime", {})
        active = runtime.get("devices", []) if time.time() - runtime.get("time", 0) < 30 else []
        rows = self.store.all("SELECT d.mac,d.name,d.agent_id,d.client_id,d.last_seen,d.created_at,a.name AS agent_name "
                              "FROM devices d JOIN agents a ON a.id=d.agent_id ORDER BY d.created_at")
        for row in rows:
            row["online"] = row["mac"] in active
        return rows

    async def overview(self, request):
        runtime = self.store.setting("runtime", {})
        devices = self.devices()
        return web.json_response({"devices": devices, "agents": self.store.all("SELECT * FROM agents ORDER BY updated_at"),
            "messages": self.store.one("SELECT count(*) AS n FROM messages")["n"],
            "engine_online": time.time() - runtime.get("time", 0) < 30,
            "model": self.model_public(), "public_url": self.config.public_url, "ws_url": self.config.ws_url})

    async def agents(self, request):
        if request.method == "GET":
            return web.json_response(self.store.all("SELECT * FROM agents ORDER BY updated_at"))
        data = await request.json()
        name, prompt = text(data, "name", 80), text(data, "prompt", 8000)
        voice = data.get("voice")
        if voice not in VOICES:
            raise ValueError("请选择支持的中文音色")
        rate = number(data, "rate", -50, 50, True)
        agent_id = request.match_info.get("id", uuid.uuid4().hex)
        if request.method == "PUT":
            changed = self.store.execute("UPDATE agents SET name=?,prompt=?,voice=?,rate=?,updated_at=? WHERE id=?",
                (name, prompt, voice, rate, int(time.time()), agent_id))
            if not changed:
                raise web.HTTPNotFound()
        else:
            self.store.execute("INSERT INTO agents VALUES(?,?,?,?,?,?)", (agent_id, name, prompt, voice, rate, int(time.time())))
        return web.json_response({"id": agent_id, "message": "已保存，下次新建语音连接时生效"})

    async def device_list(self, request):
        if request.method == "GET":
            return web.json_response(self.devices())
        data = await request.json()
        mac, name, agent_id = mac_address(data.get("mac")), text(data, "name", 80), text(data, "agent_id", 40)
        if not self.store.one("SELECT id FROM agents WHERE id=?", (agent_id,)):
            raise ValueError("所选角色不存在")
        if self.store.one("SELECT mac FROM devices WHERE mac=?", (mac,)):
            raise web.HTTPConflict(text="该设备已添加")
        self.store.execute("INSERT INTO devices(mac,name,agent_id,enrollment_key,created_at) VALUES(?,?,?,?,?)",
                           (mac, name, agent_id, secrets.token_urlsafe(32), int(time.time())))
        return web.json_response({"mac": mac})

    async def device_update(self, request):
        mac = mac_address(request.match_info["mac"])
        data = await request.json()
        name, agent_id = text(data, "name", 80), text(data, "agent_id", 40)
        if not self.store.one("SELECT id FROM agents WHERE id=?", (agent_id,)):
            raise ValueError("所选角色不存在")
        if not self.store.execute("UPDATE devices SET name=?,agent_id=? WHERE mac=?", (name, agent_id, mac)):
            raise web.HTTPNotFound()
        return web.json_response({"ok": True})

    async def connection_url(self, request):
        row = self.store.one("SELECT enrollment_key FROM devices WHERE mac=?", (mac_address(request.match_info["mac"]),))
        if not row:
            raise web.HTTPNotFound()
        return web.json_response({"ota_url": f"{self.config.public_url}/connect/{row['enrollment_key']}/ota/",
                                  "local_only": urlsplit(self.config.public_url).hostname in ("127.0.0.1", "localhost")})

    def model_public(self):
        config = self.store.setting("model")
        return {key: value for key, value in config.items() if key != "api_key"} | {"has_api_key": bool(config["api_key"])}

    async def model(self, request):
        if request.method == "GET":
            return web.json_response(self.model_public())
        data = await request.json()
        provider = data.get("provider")
        if provider not in ("ollama", "openai"):
            raise ValueError("不支持的模型接入方式")
        base_url = http_url(text(data, "base_url", 500))
        old = self.store.setting("model")
        key = data.get("api_key", "")
        if not isinstance(key, str) or len(key) > 4096:
            raise ValueError("API Key 格式不正确")
        if not key and provider == old["provider"] and base_url == old["base_url"] and not data.get("clear_key"):
            key = old["api_key"]
        if provider == "openai" and not key:
            raise ValueError("请输入 API Key；切换服务地址时需要重新填写")
        self.store.save_setting("model", {"provider": provider, "base_url": base_url, "api_key": key,
            "model": text(data, "model", 150), "temperature": number(data, "temperature", 0, 2),
            "max_tokens": number(data, "max_tokens", 32, 8192, True)})
        return web.json_response(self.model_public())

    async def completion(self, messages):
        model = self.store.setting("model")
        async with ClientSession(timeout=ClientTimeout(total=90), trust_env=False) as client:
            try:
                async with client.post(model["base_url"] + "/chat/completions", json={"model": model["model"],
                    "messages": messages, "temperature": model["temperature"], "max_tokens": model["max_tokens"], "stream": False},
                    headers={"Authorization": "Bearer " + (model["api_key"] or "ollama")}) as response:
                    if response.status != 200:
                        raise web.HTTPBadGateway(text=f"模型服务返回 HTTP {response.status}，请检查模型与密钥配置")
                    payload = await response.json()
                    answer = payload["choices"][0]["message"]["content"]
                    if not isinstance(answer, str) or not answer.strip():
                        raise ValueError("模型返回空内容")
                    return answer
            except web.HTTPException:
                raise
            except Exception:
                raise web.HTTPBadGateway(text="模型连接失败或响应格式不兼容，请检查服务地址和模型名称")

    async def model_test(self, request):
        started = time.monotonic()
        answer = await self.completion([{"role": "user", "content": "请用一句简短的中文打招呼。"}])
        return web.json_response({"reply": answer, "latency_ms": round((time.monotonic() - started) * 1000)})

    async def chat(self, request):
        data = await request.json()
        agent = self.store.one("SELECT * FROM agents WHERE id=?", (text(data, "agent_id", 40),))
        if not agent:
            raise web.HTTPNotFound()
        content = text(data, "text", 2000)
        session_id = data.get("session_id") or uuid.uuid4().hex
        if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise ValueError("会话编号格式不正确")
        if session_id in self.chat_busy:
            raise web.HTTPConflict(text="上一条回复还在生成")
        existing = self.store.one("SELECT agent_id,device_id FROM messages WHERE session_id=?", (session_id,))
        if existing and (existing["agent_id"] != agent["id"] or existing["device_id"] is not None):
            raise web.HTTPConflict(text="请新建测试会话")
        self.chat_busy.add(session_id)
        try:
            history = self.store.all("SELECT role,content FROM messages WHERE session_id=? AND role IN ('user','assistant') "
                                      "ORDER BY created_at DESC LIMIT 20", (session_id,))[::-1]
            messages = [{"role": "system", "content": agent["prompt"]}, *history, {"role": "user", "content": content}]
            answer = await self.completion(messages)
            now = int(time.time() * 1000)
            with self.store.connect() as db:
                for index, (role, value) in enumerate((("user", content), ("assistant", answer))):
                    db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, None, agent["id"], session_id, role, value, now + index))
            return web.json_response({"session_id": session_id, "reply": answer})
        finally:
            self.chat_busy.discard(session_id)

    async def history(self, request):
        limit = min(max(int(request.query.get("limit", "100")), 1), 200)
        rows = self.store.all("SELECT m.*,a.name AS agent_name,d.name AS device_name FROM messages m "
            "JOIN agents a ON a.id=m.agent_id LEFT JOIN devices d ON d.mac=m.device_id ORDER BY m.created_at DESC LIMIT ?", (limit,))
        return web.json_response(rows)

    async def ota(self, request):
        device = self.store.one("SELECT * FROM devices WHERE enrollment_key=?", (request.match_info["key"],))
        if not device:
            raise web.HTTPNotFound()
        mac = mac_address(request.headers.get("Device-Id", ""))
        client_id = request.headers.get("Client-Id", "")
        if mac != device["mac"] or not 1 <= len(client_id) <= 128:
            raise web.HTTPForbidden(text="设备身份不匹配")
        if device["client_id"] and device["client_id"] != client_id:
            raise web.HTTPForbidden(text="设备连接 ID 已绑定，请在本机管理端处理后再重新配网")
        body = await request.json()
        version = str(body.get("application", {}).get("version", "2.5.3"))[:60]
        self.store.execute("UPDATE devices SET client_id=?,last_seen=? WHERE mac=?", (client_id, int(time.time()), mac))
        return web.json_response({"server_time": {"timestamp": int(time.time() * 1000), "timezone_offset": 480},
            "firmware": {"version": version, "url": ""},
            "websocket": {"url": self.config.ws_url, "version": 1,
                          "token": device_token(self.config.secrets["device"], client_id, mac)}})

    async def internal(self, request):
        path = request.match_info["tail"]
        data = await request.json() if request.can_read_body else {}
        model = self.store.setting("model")
        if path == "config/server-base":
            agent = self.store.one("SELECT * FROM agents ORDER BY updated_at LIMIT 1")
            return self.ok(self.config.engine_config(agent, model))
        if path in ("config/agent-models", "device/allow"):
            mac = mac_address(data.get("macAddress"))
            device = self.store.one("SELECT * FROM devices WHERE mac=?", (mac,))
            if not device or not device["client_id"] or device["client_id"] != data.get("clientId"):
                return web.json_response({"code": 10041, "msg": "设备未绑定或身份不匹配"})
            if path == "device/allow":
                return self.ok(True)
            self.store.execute("UPDATE devices SET last_seen=? WHERE mac=?", (int(time.time()), mac))
            agent = self.store.one("SELECT * FROM agents WHERE id=?", (device["agent_id"],))
            return self.ok(self.config.agent_config(agent, model))
        if path == "config/correct-words":
            return self.ok([])
        if path == "runtime":
            devices = [mac_address(mac) for mac in data.get("devices", [])[:1000]]
            self.store.save_setting("runtime", {"time": time.time(), "devices": devices})
            return self.ok(True)
        if path == "agent/chat-history/report":
            mac = mac_address(data.get("macAddress"))
            device = self.store.one("SELECT * FROM devices WHERE mac=?", (mac,))
            if not device:
                return web.json_response({"code": 10041, "msg": "设备不存在"})
            content = text(data, "content", 16000)
            session_id = text(data, "sessionId", 128)
            role = {1: "user", 2: "assistant", 3: "tool"}.get(data.get("chatType"))
            if not role:
                raise ValueError("消息类型不支持")
            timestamp = number(data, "reportTime", 0, 99999999999999, True)
            key = hashlib.sha256(json.dumps([mac, session_id, role, content, timestamp], ensure_ascii=False).encode()).hexdigest()
            self.store.execute("INSERT OR IGNORE INTO messages VALUES(?,?,?,?,?,?,?)",
                               (key, mac, device["agent_id"], session_id, role, content, timestamp))
            return self.ok(True)
        # Upstream title/summary tasks are optional. No synthetic summaries are presented.
        if re.fullmatch(r"agent/chat-(?:summary|title)/[^/]+/(?:save|generate)", path):
            return self.ok(None)
        raise web.HTTPNotFound()


CONTROLLER = web.AppKey("controller", Controller)


def create_app(config=None):
    controller = Controller(config or Config())

    @web.middleware
    async def guard(request, handler):
        try:
            config = controller.config
            allowed_hosts = {"localhost", "127.0.0.1", "::1", urlsplit(config.public_url).hostname}
            if request.url.host not in allowed_hosts:
                raise web.HTTPForbidden(text="不支持的访问地址，请配置 ESP_PUBLIC_URL")
            if request.path.startswith("/xiaozhi/"):
                expected = "Bearer " + config.secrets["internal"]
                if not hmac.compare_digest(request.headers.get("Authorization", ""), expected):
                    raise web.HTTPUnauthorized(text="需要内部服务凭据")
            elif request.path.startswith("/api/"):
                if request.method not in ("GET", "HEAD"):
                    origin = request.headers.get("Origin")
                    if origin and origin != f"{request.scheme}://{request.host}" and origin != config.public_url:
                        raise web.HTTPForbidden(text="跨站请求已拒绝")
                    if request.content_type != "application/json":
                        raise web.HTTPUnsupportedMediaType(text="请使用 JSON 请求")
                if request.path not in ("/api/bootstrap", "/api/login", "/api/setup", "/api/health") and not controller.user(request):
                    raise web.HTTPUnauthorized(text="请先登录")
            response = await handler(request)
        except web.HTTPException as error:
            response = web.json_response({"error": error.text or error.reason}, status=error.status)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            response = web.json_response({"error": "输入格式不正确，请检查填写内容"}, status=400)
        except Exception:
            response = web.json_response({"error": "服务暂时无法处理请求"}, status=500)
        response.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"})
        return response

    app = web.Application(middlewares=[guard], client_max_size=128 * 1024)
    app[CONTROLLER] = controller
    app.router.add_get("/api/bootstrap", controller.identity)
    async def health(request):
        return web.json_response({"status": "ok", "service": "esp32-control"})

    async def index(request):
        return web.FileResponse(ROOT / "web" / "index.html")

    app.router.add_get("/api/health", health)
    app.router.add_post("/api/setup", controller.session)
    app.router.add_post("/api/login", controller.session)
    app.router.add_post("/api/logout", controller.logout)
    app.router.add_get("/api/overview", controller.overview)
    app.router.add_get("/api/agents", controller.agents)
    app.router.add_post("/api/agents", controller.agents)
    app.router.add_put("/api/agents/{id}", controller.agents)
    app.router.add_get("/api/devices", controller.device_list)
    app.router.add_post("/api/devices", controller.device_list)
    app.router.add_put("/api/devices/{mac}", controller.device_update)
    app.router.add_get("/api/devices/{mac}/connection", controller.connection_url)
    app.router.add_get("/api/model", controller.model)
    app.router.add_put("/api/model", controller.model)
    app.router.add_post("/api/model/test", controller.model_test)
    app.router.add_post("/api/chat", controller.chat)
    app.router.add_get("/api/history", controller.history)
    app.router.add_post("/connect/{key}/ota/", controller.ota)
    app.router.add_post("/xiaozhi/{tail:.*}", controller.internal)
    app.router.add_get("/", index)
    app.router.add_static("/static/", ROOT / "web")
    return app
