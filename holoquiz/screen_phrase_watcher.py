from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
from typing import Any, Callable
import json
from urllib.request import urlopen


@dataclass(frozen=True)
class ScreenReadRegion:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Screen read region width and height must be positive.")

    def as_pyautogui_region(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


@dataclass(frozen=True)
class TextMatchEvent:
    trigger_phrase: str
    trigger_text: str
    result_text: str


@dataclass(frozen=True)
class ScreenPhraseCheckResult:
    trigger_phrase: str
    trigger_region: ScreenReadRegion | None
    result_region: ScreenReadRegion | None
    trigger_text: str
    trigger_matched: bool
    result_text: str
    event: TextMatchEvent | None
    reason: str


TextReader = Callable[[ScreenReadRegion], str]
SCREEN_PHRASE_SOURCE_OCR = "ocr"
SCREEN_PHRASE_SOURCE_TITLE_API = "title_api"


class TitleDataClient:
    def __init__(
        self,
        data_url: str = "http://127.0.0.1:8026/data/title",
        health_url: str = "http://127.0.0.1:8026/health",
        timeout_seconds: float = 2.0,
        urlopen_func: Callable[..., Any] | None = None,
    ) -> None:
        self.data_url = data_url
        self.health_url = health_url
        self.timeout_seconds = timeout_seconds
        self._urlopen = urlopen_func or urlopen

    def _get_json(self, url: str) -> dict[str, Any]:
        with self._urlopen(url, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected a JSON object from {url}.")
        return payload

    def read_title(self) -> tuple[str, str]:
        payload = self._get_json(self.data_url)
        return str(payload.get("subtitle") or ""), str(payload.get("title") or "")

    def health(self) -> dict[str, Any]:
        return self._get_json(self.health_url)


def normalize_screen_text(text: str) -> str:
    words = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    return " ".join(words)


def phrase_found_in_text(phrase: str, text: str) -> bool:
    clean_phrase = normalize_screen_text(phrase)
    if not clean_phrase:
        return False
    clean_text = normalize_screen_text(text)
    return re.search(re.escape(clean_phrase), clean_text) is not None


class ScreenPhraseWatcher:
    def __init__(
        self,
        text_reader: TextReader,
        title_client: TitleDataClient | None = None,
    ) -> None:
        self._text_reader = text_reader
        self._lock = RLock()
        self._trigger_region: ScreenReadRegion | None = None
        self._result_region: ScreenReadRegion | None = None
        self._trigger_phrase = ""
        self._last_result_text = ""
        self._source = SCREEN_PHRASE_SOURCE_OCR
        self._title_client = title_client or TitleDataClient()

    def set_source(self, source: str) -> None:
        if source not in {SCREEN_PHRASE_SOURCE_OCR, SCREEN_PHRASE_SOURCE_TITLE_API}:
            raise ValueError(f"Unknown screen phrase source: {source}")
        with self._lock:
            self._source = source
            self._last_result_text = ""

    def get_source(self) -> str:
        with self._lock:
            return self._source

    def check_api_health(self) -> dict[str, Any]:
        return self._title_client.health()

    def set_trigger_region(self, region: ScreenReadRegion) -> None:
        with self._lock:
            self._trigger_region = region
            self._last_result_text = ""

    def set_result_region(self, region: ScreenReadRegion) -> None:
        with self._lock:
            self._result_region = region
            self._last_result_text = ""

    def get_trigger_region(self) -> ScreenReadRegion | None:
        with self._lock:
            return self._trigger_region

    def get_result_region(self) -> ScreenReadRegion | None:
        with self._lock:
            return self._result_region

    def set_trigger_phrase(self, phrase: str) -> None:
        with self._lock:
            self._trigger_phrase = phrase.strip()
            self._last_result_text = ""

    def is_ready(self) -> bool:
        with self._lock:
            if self._source == SCREEN_PHRASE_SOURCE_TITLE_API:
                return bool(self._trigger_phrase)
            return (
                self._trigger_region is not None
                and self._result_region is not None
                and bool(self._trigger_phrase)
            )

    def check_once(self) -> TextMatchEvent | None:
        return self.check_once_detailed().event

    def check_once_detailed(self) -> ScreenPhraseCheckResult:
        with self._lock:
            trigger_region = self._trigger_region
            result_region = self._result_region
            trigger_phrase = self._trigger_phrase
            source = self._source

        if source == SCREEN_PHRASE_SOURCE_TITLE_API:
            if not trigger_phrase:
                return ScreenPhraseCheckResult(
                    trigger_phrase, None, None, "", False, "", None,
                    "missing trigger phrase",
                )
            trigger_text, result_text = self._title_client.read_title()
            return self._build_result(
                trigger_phrase, None, None, trigger_text.strip(), result_text.strip()
            )

        if trigger_region is None or result_region is None or not trigger_phrase:
            return ScreenPhraseCheckResult(
                trigger_phrase=trigger_phrase,
                trigger_region=trigger_region,
                result_region=result_region,
                trigger_text="",
                trigger_matched=False,
                result_text="",
                event=None,
                reason="missing trigger phrase or screen area",
            )

        trigger_text = self._text_reader(trigger_region).strip()
        if not phrase_found_in_text(trigger_phrase, trigger_text):
            return ScreenPhraseCheckResult(
                trigger_phrase=trigger_phrase,
                trigger_region=trigger_region,
                result_region=result_region,
                trigger_text=trigger_text,
                trigger_matched=False,
                result_text="",
                event=None,
                reason="trigger phrase not found",
            )

        result_text = self._text_reader(result_region).strip()
        return self._build_result(
            trigger_phrase, trigger_region, result_region, trigger_text, result_text
        )

    def _build_result(
        self,
        trigger_phrase: str,
        trigger_region: ScreenReadRegion | None,
        result_region: ScreenReadRegion | None,
        trigger_text: str,
        result_text: str,
    ) -> ScreenPhraseCheckResult:
        if not phrase_found_in_text(trigger_phrase, trigger_text):
            return ScreenPhraseCheckResult(
                trigger_phrase, trigger_region, result_region, trigger_text, False,
                "", None, "trigger phrase not found",
            )
        clean_result_text = normalize_screen_text(result_text)
        if not clean_result_text:
            return ScreenPhraseCheckResult(
                trigger_phrase=trigger_phrase,
                trigger_region=trigger_region,
                result_region=result_region,
                trigger_text=trigger_text,
                trigger_matched=True,
                result_text=result_text,
                event=None,
                reason="result text empty",
            )

        with self._lock:
            if clean_result_text == self._last_result_text:
                return ScreenPhraseCheckResult(
                    trigger_phrase=trigger_phrase,
                    trigger_region=trigger_region,
                    result_region=result_region,
                    trigger_text=trigger_text,
                    trigger_matched=True,
                    result_text=result_text,
                    event=None,
                    reason="result text repeated",
                )
            self._last_result_text = clean_result_text

        event = TextMatchEvent(
            trigger_phrase=trigger_phrase,
            trigger_text=trigger_text,
            result_text=result_text,
        )
        return ScreenPhraseCheckResult(
            trigger_phrase=trigger_phrase,
            trigger_region=trigger_region,
            result_region=result_region,
            trigger_text=trigger_text,
            trigger_matched=True,
            result_text=result_text,
            event=event,
            reason="matched",
        )
