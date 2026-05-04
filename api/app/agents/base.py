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
    timeout=httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0),
)
_MODEL       = "gpt-4.1"
_MAX_STEPS   = 15
_MAX_RETRIES = 3
_RETRY_DELAY = 3

log = logging.getLogger(__name__)



class BaseAgent:

    def __init__(self, tenant_id: str):
        self.tenant_id  = tenant_id
        self._model     = _MODEL
        self._reasoning: dict | None = None
        self.tool_messages: list[dict] = []
        self.usage: dict = {"input_tokens": 0, "output_tokens": 0}

    def prompt(self) -> str:
        return "You are a helpful assistant."

    def tools(self) -> list[dict]:
        return []

    def _execute(self, name: str, args: dict) -> list:
        return []

    def run(self, history: list[dict]) -> Generator:
        self.tool_messages = []
        input_messages = [{"role": "system", "content": self.prompt()}, *history]
        return self._loop(input_messages)

    def _loop(self, input_messages: list) -> Generator:
        for step in range(_MAX_STEPS):
            if step > 0:
                yield {"type": "thinking"}

            tool_calls:     list[dict]    = []
            tool_args:      dict[str, str] = {}
            active_call_id: str | None    = None
            response_deltas: list[str]    = []
            response_text   = ""
            log.debug(f"[loop] agent={type(self).__name__} step={step + 1}")

            stream = None
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    kwargs = dict(
                        model=self._model,
                        input=input_messages,
                        tools=self.tools(),
                        stream=True,
                    )
                    if self._reasoning:
                        kwargs["reasoning"] = self._reasoning
                    stream = _client.responses.create(**kwargs)
                    break
                except Exception as e:
                    if attempt < _MAX_RETRIES:
                        log.warning(f"[agent] OpenAI error (attempt {attempt}/{_MAX_RETRIES}): {e} — retrying in {_RETRY_DELAY}s")
                        time.sleep(_RETRY_DELAY)
                    else:
                        raise

            for event in stream:
                if event.type == "response.output_text.delta":
                    response_text += event.delta
                    response_deltas.append(event.delta)

                elif event.type == "response.output_item.added":
                    if event.item.type == "function_call":
                        active_call_id = event.item.call_id
                        tool_calls.append({"call_id": active_call_id, "name": event.item.name})
                        tool_args[active_call_id] = ""

                elif event.type == "response.function_call_arguments.delta":
                    if active_call_id in tool_args:
                        tool_args[active_call_id] += event.delta

                elif event.type == "response.completed":
                    if hasattr(event.response, "usage") and event.response.usage:
                        u = event.response.usage
                        self.usage["input_tokens"]  += getattr(u, "input_tokens", 0)
                        self.usage["output_tokens"] += getattr(u, "output_tokens", 0)
                    if response_text:
                        log.debug(f"[response] agent={type(self).__name__} step={step + 1} text={response_text!r}")
                    if not tool_calls:
                        for delta in response_deltas:
                            yield {"type": "token", "value": delta}
                        return
                    if response_text:
                        yield {"type": "status", "value": response_text}
                    break

            if not tool_calls:
                return

            fc_msgs = []
            fr_msgs = []
            for tc in tool_calls:
                call_id = tc["call_id"]
                try:
                    args = json.loads(tool_args.get(call_id, "") or "{}")
                except json.JSONDecodeError:
                    args = {}

                filtered = {k: v for k, v in args.items() if v is not None and v != ""}
                log.info(f"[tool_call] {tc['name']}({filtered})")
                log.debug(f"[tool_call] agent={type(self).__name__} step={step + 1} {tc['name']}({filtered})")
                result = self._execute(tc["name"], args)
                if result is None:
                    result = []
                log.info(f"[tool_result] {tc['name']} → {len(result)} results")
                log.debug(f"[tool_result] {tc['name']} payload={json.dumps(result)[:500]}")

                fc_msgs.append({
                    "type": "function_call",
                    "name": tc["name"],
                    "call_id": call_id,
                    "arguments": tool_args.get(call_id, ""),
                })
                fr_msgs.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result),
                })

            input_messages.extend(fc_msgs)
            input_messages.extend(fr_msgs)
            self.tool_messages.extend(fc_msgs)
            self.tool_messages.extend(fr_msgs)

        yield {"type": "token", "value": "\n\nSorry, I couldn't complete the request."}
