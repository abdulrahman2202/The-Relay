"""Conservative prompt guard, separate from measured provider token usage."""

import json
from typing import Any


def prompt_upper_bound(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> int:
    """Budget UTF-8 bytes plus framing, not MiniLM tokens or an exact Groq count.

    GPT-OSS uses byte-level tokenization. Budgeting one token per serialized byte
    leaves substantial headroom, with extra allowance for Harmony/tool framing.
    A different model's tokenizer/template needs its own budget validation.
    """
    payload = json.dumps({"messages": messages, "tools": tools or []}, ensure_ascii=False)
    return len(payload.encode("utf-8")) + 256 * len(messages) + 512
