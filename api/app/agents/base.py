import json
import os
from typing import Generator

from openai import OpenAI

_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_MODEL = "gpt-4.1"
_MAX_STEPS = 5

# ANSI colors
_CYAN   = "\033[96m"
_YELLOW = "\033[93m"
_GREEN  = "\033[92m"
_DIM    = "\033[2m"
_RESET  = "\033[0m"


def _log_tool_call(name: str, args: dict) -> None:
    params = ", ".join(f"{k}={repr(v)}" for k, v in args.items())
    print(f"\n{_CYAN}⚙ tool call:{_RESET} {_YELLOW}{name}{_RESET}({_DIM}{params}{_RESET})")


def _log_answer_start() -> None:
    print(f"\n{_GREEN}", end="", flush=True)


def _log_answer_end() -> None:
    print(_RESET, end="", flush=True)


class BaseAgent:

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self._citations: list[str] = []

    def prompt(self) -> str:
        return "You are a helpful assistant."

    def tools(self) -> list[dict]:
        return []

    def _execute(self, name: str, args: dict) -> list:
        return []

    def run(self, history: list[dict]) -> tuple[Generator, list[str]]:
        self._citations = []
        input_messages = [{"role": "system", "content": self.prompt()}, *history]
        return self._loop(input_messages), self._citations

    def _loop(self, input_messages: list) -> Generator:
        for _ in range(_MAX_STEPS):
            tool_call_name = None
            tool_call_id = None
            tool_call_args = ""
            answer_started = False

            stream = _client.responses.create(
                model=_MODEL,
                input=input_messages,
                tools=self.tools(),
                stream=True,
            )

            for event in stream:
                if event.type == "response.output_text.delta":
                    if not answer_started:
                        _log_answer_start()
                        answer_started = True
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
                    if answer_started:
                        _log_answer_end()
                    return

            if not tool_call_name:
                return

            try:
                args = json.loads(tool_call_args or "{}")
            except json.JSONDecodeError:
                args = {}

            _log_tool_call(tool_call_name, args)

            result = self._execute(tool_call_name, args)

            input_messages.append({
                "type": "function_call",
                "name": tool_call_name,
                "call_id": tool_call_id,
                "arguments": tool_call_args,
            })
            input_messages.append({
                "type": "function_call_output",
                "call_id": tool_call_id,
                "output": json.dumps(result),
            })

        yield "\n\nSorry, I couldn't complete the request."
