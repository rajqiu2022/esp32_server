"""Virtual lamp for a live ASR -> model -> device MCP smoke test; no hardware."""
import asyncio
import json


class LightFixture:
    def __init__(self):
        self.on = False
        self.calls = []
        self.ready = asyncio.Event()
        self.incoming = asyncio.Queue()
        self.error = None

    async def read(self, ws):
        try:
            async for message in ws:
                obj = json.loads(message) if isinstance(message, str) else {}
                payload = obj.get("payload", {}) if obj.get("type") == "mcp" else {}
                method = payload.get("method")
                if not method:
                    await self.incoming.put(message)
                    continue
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "virtual-lamp-test", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "self.light.set_power",
                        "description": "Turn the onboard lamp on or off. Execute when asked to open or close the light.",
                        "inputSchema": {"type": "object", "properties": {"on": {"type": "boolean"}}, "required": ["on"]}}]}
                    self.ready.set()
                elif method == "tools/call":
                    params = payload["params"]
                    assert params["name"] == "self.light.set_power", "Unexpected tool call"
                    assert type(params["arguments"]["on"]) is bool, "Invalid lamp argument"
                    self.on = params["arguments"]["on"]
                    self.calls.append(params)
                    result = {"content": [{"type": "text", "text": json.dumps({"on": self.on})}], "isError": False}
                else:
                    continue
                await ws.send(json.dumps({"type": "mcp", "payload": {"jsonrpc": "2.0", "id": payload["id"], "result": result}}))
        except Exception as exc:
            self.error = exc
            await self.incoming.put(exc)

    async def recv(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item
