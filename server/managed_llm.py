"""Managed voice provider; upstream transport plus fresh server context."""
from core.providers.llm.openai.openai import LLMProvider as OpenAIProvider
from server.live_context import with_live_context


class LLMProvider(OpenAIProvider):
    def response(self, session_id, dialogue, **kwargs):
        return super().response(session_id, with_live_context(dialogue, self.model_name), **kwargs)

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        return super().response_with_functions(
            session_id, with_live_context(dialogue, self.model_name), functions, **kwargs)
