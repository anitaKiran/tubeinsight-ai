"""One bounded OpenAI client per agent request; native tools and JSON schema."""
from contextlib import contextmanager

from langchain_openai import ChatOpenAI
from openai import OpenAI

from app.agent.observability import operation
from app.rag.providers import provider_errors
from app.schemas.error import ApiException


class AgentModel:
    def __init__(self, settings, budget, client):
        self.settings, self.budget, self.client = settings, budget, client

    def invoke(self, messages, *, tools=None, schema=None, name="agent.model"):
        self.budget.model()
        timeout = min(8.0, self.settings.api_timeout, self.budget.remaining())
        with operation(name, "llm") as metadata, provider_errors("OpenAI"):
            client = self.client.with_options(timeout=timeout)
            model = ChatOpenAI(api_key=self.settings.openai_key, model=self.settings.chat_model,
                root_client=client, client=client.chat.completions, timeout=timeout,
                max_retries=0, max_tokens=1200, reasoning_effort="none" if self.settings.chat_model.startswith(("gpt-5", "gpt-6")) else None,
                use_responses_api=False)
            if tools is not None:
                runnable = model.bind_tools(tools, tool_choice="required", parallel_tool_calls=True)
            elif schema is not None:
                runnable = model.with_structured_output(schema, method="json_schema", strict=True, include_raw=True)
            else:
                runnable = model
            result = runnable.invoke(messages)
            raw = result.get("raw") if schema is not None else result
            usage = getattr(raw, "usage_metadata", None) or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                if isinstance(usage.get(key), int):
                    metadata[key] = usage[key]
            if schema is not None:
                if result.get("parsing_error") is not None or result.get("parsed") is None:
                    raise ApiException(502, "RAG_RESPONSE_INVALID", "The model did not return a valid grounded response.")
                return result["parsed"]
            return result


@contextmanager
def open_agent_model(settings, budget):
    # These models are verified for Chat Completions function calling with
    # reasoning_effort=none. Unknown configurations fail instead of disabling tools.
    if not settings.chat_model.startswith(("gpt-6-luna", "gpt-6-sol", "gpt-5", "gpt-4o", "gpt-4.1")):
        raise ApiException(500, "MODEL_TOOL_INCOMPATIBLE", "Configure a model supported by the native tool-calling agent, such as gpt-6-luna.")
    with provider_errors("OpenAI"), OpenAI(api_key=settings.openai_key, timeout=8, max_retries=0) as client:
        yield AgentModel(settings, budget, client)
