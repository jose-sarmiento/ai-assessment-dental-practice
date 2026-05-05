import json
import logging
import time
from typing import Generator

from ..db.connection import get_conn
from .base import BaseAgent, _client, _MAX_STEPS, _MAX_RETRIES, _RETRY_DELAY

log = logging.getLogger(__name__)

_DEFAULT_MAX_PAGES  = 20
_PAGES_PER_BATCH    = 4
_KEEP_TOOL_PAIRS    = 2  # sliding window — keep last N tool call pairs in history


class SummarizerAgent(BaseAgent):

    def __init__(self, tenant_id: str, document_id: str, max_pages: int = _DEFAULT_MAX_PAGES):
        super().__init__(tenant_id)
        self.document_id = document_id
        self.max_pages   = max_pages
        self._summary    = ""
        self._meta       = self._fetch_metadata()

    def prompt(self) -> str:
        if not self._meta:
            return "You are a document summarizer."

        source      = self._meta["source"]
        total_pages = min(self._meta["total_pages"], self.max_pages)

        return (
            f"You are a high-precision document summarizer.\n\n"

            f"Document: '{source}'\n"
            f"Summarize pages 1 to {total_pages} by reading {_PAGES_PER_BATCH} pages at a time.\n\n"

            "=== OBJECTIVE ===\n"
            "Produce a faithful, structured, and non-redundant summary of the document.\n\n"

            "=== STRICT RULES (CRITICAL) ===\n"
            "- ONLY use information explicitly present in the text\n"
            "- DO NOT hallucinate, infer, or add missing details\n"
            "- Preserve ALL important numbers, limits, conditions, and rules exactly\n"
            "- Preserve uncertainty (e.g., 'may', 'can', 'up to')\n"
            "- DO NOT repeat information already summarized in previous batches\n"
            "- If content overlaps, consolidate instead of repeating\n\n"

            "=== WORKFLOW (REPEAT UNTIL DONE) ===\n"
            f"1. Call read_pages(page_from, page_to) — read exactly {_PAGES_PER_BATCH} pages sequentially\n"
            "2. Extract ONLY new, non-duplicated information\n"
            "3. Call save_summary(text) using the STRUCTURED FORMAT below\n"
            "4. Move to the next pages\n\n"

            f"When all pages up to {total_pages} are processed:\n"
            "→ Produce a FINAL COMPILED SUMMARY using all saved summaries\n\n"

            "=== FORMAT FOR EACH save_summary CALL ===\n"
            "Use this structure strictly:\n\n"
            "Pages: <page range>\n"
            "Key Points:\n"
            "- ...\n"
            "- ...\n\n"
            "Rules / Requirements (if any):\n"
            "- ...\n\n"
            "Important Numbers / Limits (if any):\n"
            "- ...\n\n"
            "Notes (only if necessary):\n"
            "- ...\n\n"

            "=== FINAL SUMMARY REQUIREMENTS ===\n"
            "The final compiled summary must:\n"
            "- Be well-structured (group related topics)\n"
            "- Remove duplication across batches\n"
            "- Preserve all critical rules, steps, and constraints\n"
            "- Be concise but complete\n"
            "- Be usable without reading the original document\n\n"

            "=== QUALITY BAR ===\n"
            "A good summary = maximum important information with minimum words, without losing meaning.\n"
        )

    def tools(self) -> list[dict]:
        total_pages = min(self._meta["total_pages"], self.max_pages) if self._meta else self.max_pages
        return [
            {
                "type": "function",
                "name": "read_pages",
                "description": (
                    f"Read a range of pages from the document (pages 1 to {total_pages}). "
                    f"Read {_PAGES_PER_BATCH} pages at a time in sequential order."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "page_from": {"type": "integer", "description": "First page of the range (inclusive, 1-based)"},
                        "page_to":   {"type": "integer", "description": f"Last page of the range (inclusive, max {total_pages})"},
                    },
                    "required": ["page_from", "page_to"],
                },
            },
            {
                "type": "function",
                "name": "save_summary",
                "description": "Append a concise summary of the pages just read to the running summary.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "Summary text to append"},
                    },
                    "required": ["text"],
                },
            },
        ]

    def _execute(self, name: str, args: dict) -> list:
        if name == "read_pages":
            return self._read_pages(args.get("page_from", 1), args.get("page_to", 1))
        if name == "save_summary":
            return self._save_summary(args.get("text", ""))
        return []

    def _read_pages(self, page_from: int, page_to: int) -> list[dict]:
        page_to = min(page_to, self.max_pages)
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT text, page, chunk_index
                    FROM data_sources
                    WHERE tenant_id = %s AND document_id = %s
                      AND page >= %s AND page <= %s
                    ORDER BY page, chunk_index
                    """,
                    (self.tenant_id, self.document_id, page_from, page_to),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return [{"content": f"No content for pages {page_from}–{page_to}.", "pages": f"{page_from}-{page_to}"}]

        text = "\n\n".join(r[0] for r in rows)
        log.debug(f"[summarizer] read pages {page_from}-{page_to} chunks={len(rows)}")
        return [{"content": text, "pages": f"{page_from}-{page_to}", "chunks": len(rows)}]

    def _save_summary(self, text: str) -> list[dict]:
        if self._summary:
            self._summary += "\n\n" + text
        else:
            self._summary = text
        log.debug(f"[summarizer] saved summary chunk ({len(text)} chars, total={len(self._summary)})")
        return [{"saved": True, "total_length": len(self._summary)}]

    def _fetch_metadata(self) -> dict | None:
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source, MAX(page) AS total_pages, COUNT(*) AS total_chunks
                    FROM data_sources
                    WHERE tenant_id = %s AND document_id = %s
                    GROUP BY source
                    """,
                    (self.tenant_id, self.document_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {"source": row[0], "total_pages": row[1], "total_chunks": row[2]}
        finally:
            conn.close()

    def _prompt_with_summary(self) -> str:
        base = self.prompt()
        if self._summary:
            return base + f"\n\nSummary saved so far:\n{self._summary}"
        return base

    def run(self, history: list[dict]) -> Generator:
        """Custom loop: rebuilds system prompt with current summary and keeps sliding window of tool calls."""
        self.tool_messages = []
        tool_pairs: list[tuple] = []  # list of (fc_msgs, fr_msgs)

        for step in range(_MAX_STEPS):
            if step > 0:
                yield {"type": "thinking"}

            # Keep only last _KEEP_TOOL_PAIRS pairs + system + history
            recent = [msg for fc, fr in tool_pairs[-_KEEP_TOOL_PAIRS:] for msg in [*fc, *fr]]
            input_messages = [
                {"role": "system", "content": self._prompt_with_summary()},
                *history,
                *recent,
            ]

            tool_calls:     list[dict]    = []
            tool_args:      dict[str, str] = {}
            active_call_id: str | None    = None
            response_text   = ""

            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    stream = _client.responses.create(
                        model=self._model,
                        input=input_messages,
                        tools=self.tools(),
                        stream=True,
                    )
                    break
                except Exception as e:
                    if attempt < _MAX_RETRIES:
                        log.warning(f"[summarizer] error attempt {attempt}: {e} — retrying in {_RETRY_DELAY}s")
                        time.sleep(_RETRY_DELAY)
                    else:
                        raise

            for event in stream:
                if event.type == "response.output_text.delta":
                    response_text += event.delta
                    yield {"type": "token", "value": event.delta}

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
                    if not tool_calls:
                        return
                    break

            if not tool_calls:
                return

            fc_msgs, fr_msgs = [], []
            for tc in tool_calls:
                call_id = tc["call_id"]
                try:
                    args = json.loads(tool_args.get(call_id, "") or "{}")
                except json.JSONDecodeError:
                    args = {}

                if tc['name'] == 'save_summary':
                    log.info(f"[summarizer] save_summary(chars={len(args.get('text', ''))})")
                else:
                    log.info(f"[summarizer] {tc['name']}({args})")
                result = self._execute(tc["name"], args)
                if result is None:
                    result = []

                fc_msgs.append({"type": "function_call", "name": tc["name"], "call_id": call_id, "arguments": tool_args.get(call_id, "")})
                fr_msgs.append({"type": "function_call_output", "call_id": call_id, "output": json.dumps(result)})

            tool_pairs.append((fc_msgs, fr_msgs))
            self.tool_messages.extend(fc_msgs)
            self.tool_messages.extend(fr_msgs)

        yield {"type": "token", "value": "\n\nSorry, could not complete the summary."}

    def summarize(self) -> Generator:
        if not self._meta:
            def _empty():
                yield {"type": "token", "value": f"No document found for ID: {self.document_id}"}
            return _empty()

        capped = min(self._meta["total_pages"], self.max_pages)
        log.info(
            f"[summarizer] document={self.document_id} source={self._meta['source']} "
            f"pages={self._meta['total_pages']} summarizing={capped}"
        )
        history = [{"role": "user", "content": "Summarize this document now. Read all pages sequentially and save summaries as you go."}]
        return self.run(history)
