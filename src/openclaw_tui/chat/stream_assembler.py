from __future__ import annotations


def _extract_text_from_content_item(item: object, include_thinking: bool) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return ""

    kind = item.get("type")
    if isinstance(kind, str) and kind.lower() == "thinking" and not include_thinking:
        return ""

    text = item.get("text")
    if isinstance(text, str):
        return text
    content = item.get("content")
    if isinstance(content, str):
        return content
    return ""


def extract_text_from_message(message: object, include_thinking: bool) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            _extract_text_from_content_item(item, include_thinking)
            for item in content
        ]
        text = "\n".join(part for part in parts if part)
        return text.strip()

    text = message.get("text")
    if isinstance(text, str):
        return text
    return ""


class TuiStreamAssembler:
    def __init__(self) -> None:
        self._latest: dict[str, str] = {}

    def ingest_delta(self, run_id: str, message: object, include_thinking: bool) -> str:
        text = extract_text_from_message(message, include_thinking)
        if text:
            self._latest[run_id] = text
        return self._latest.get(run_id, "")

    def finalize(self, run_id: str, message: object, include_thinking: bool) -> str:
        text = extract_text_from_message(message, include_thinking)
        if text:
            self._latest[run_id] = text
        final_text = self._latest.get(run_id, "")
        self.drop(run_id)
        return final_text

    def drop(self, run_id: str) -> None:
        self._latest.pop(run_id, None)
