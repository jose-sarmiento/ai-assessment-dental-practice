import json
import logging
import os
import time
from typing import Generator

import httpx
from openai import OpenAI

_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    max_retries=0,
    timeout=httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0),
)
_MODEL       = "gpt-4.1"
_MAX_STEPS   = 15
_MAX_RETRIES = 3
_RETRY_DELAY = 3

log = logging.getLogger(__name__)


class BaseAgent:

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._citations: list[str] = []
        self.tool_messages: list[dict] = []
        self.usage: dict = {"input_tokens": 0, "output_tokens": 0}

    def prompt(self) -> str:
        return "You are a helpful assistant."

    def tools(self) -> list[dict]:
        return []

    def _execute(self, name: str, args: dict) -> list:
        return []

    def run(self, history: list[dict]) -> tuple[Generator, list[str]]:
        self._citations = []
        self.tool_messages = []
        input_messages = [{"role": "system", "content": self.prompt()}, *history]
        return self._loop(input_messages), self._citations

    def _loop(self, input_messages: list) -> Generator:
        for _ in range(_MAX_STEPS):
            tool_call_name = None
            tool_call_id = None
            tool_call_args = ""

            stream = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    stream = _client.responses.create(
                        model=_MODEL,
                        input=input_messages,
                        tools=self.tools(),
                        stream=True,
                    )
                    break
                except Exception as e:
                    if attempt < _MAX_RETRIES:
                        log.warning(f"[agent] OpenAI error (attempt {attempt}/{_MAX_RETRIES}): {e} — retrying in {_RETRY_DELAY}s")
                        time.sleep(_RETRY_DELAY)
                    else:
                        raise

            for event in stream:
                if event.type == "response.output_text.delta":
                    yield event.delta

                elif event.type == "response.output_item.added":
                    if event.item.type == "function_call":
                        tool_call_name = event.item.name
                        tool_call_id = event.item.call_id

                elif event.type == "response.function_call_arguments.delta":
                    tool_call_args += event.delta

                elif event.type == "response.output_item.done":
                    if event.item.type == "function_call":
                        break

                elif event.type == "response.completed":
                    if hasattr(event.response, "usage") and event.response.usage:
                        u = event.response.usage
                        self.usage["input_tokens"]  += getattr(u, "input_tokens", 0)
                        self.usage["output_tokens"] += getattr(u, "output_tokens", 0)
                    return

            if not tool_call_name:
                return

            try:
                args = json.loads(tool_call_args or "{}")
            except json.JSONDecodeError:
                args = {}

            filtered = {k: v for k, v in args.items() if v is not None and v != ""}
            log.info(f"[tool_call] {tool_call_name}({filtered})")
            result = self._execute(tool_call_name, args)
            log.info(f"[tool_result] {tool_call_name} → {len(result)} results")

            fc_msg = {
                "type": "function_call",
                "name": tool_call_name,
                "call_id": tool_call_id,
                "arguments": tool_call_args,
            }
            fr_msg = {
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": json.dumps(result),
            }
            input_messages.append(fc_msg)
            input_messages.append(fr_msg)
            self.tool_messages.append(fc_msg)
            self.tool_messages.append(fr_msg)

        yield "\n\nSorry, I couldn't complete the request."
