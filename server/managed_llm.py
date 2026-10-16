"""Managed voice provider; upstream transport plus fresh server context."""
from core.providers.llm.openai.openai import LLMProvider as OpenAIProvider
from server.live_context import with_live_context


class LLMProvider(OpenAIProvider):
    def response(self, session_id, dialogue, **kwargs):
        return super().response(session_id, with_live_context(dialogue, self.model_name), **kwargs)

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        messages = with_live_context(dialogue, self.model_name)
        if functions:
            messages[0]["content"] += (
                "\n设备控制必须调用本轮实际提供的对应工具，收到成功结果后才能说操作成功。"
                "开关灯、改灯色和亮度使用 self.light 工具；相对调节前先读取当前状态。"
                "没有对应工具或执行失败时如实说明，不能假装已经完成。")
        return super().response_with_functions(session_id, messages, functions, **kwargs)
