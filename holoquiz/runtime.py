from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock

from holoquiz.config import BotConfig


FIND_ANSWER_FUNCTION = "find_answer"
SCREEN_PHRASE_WATCHER_FUNCTION = "screen_phrase_watcher"


@dataclass(frozen=True)
class FunctionDefinition:
    key: str
    label: str
    enabled_by_default: bool = True


class FunctionRegistry:
    def __init__(self, functions: list[FunctionDefinition]) -> None:
        self._functions = tuple(functions)
        self._keys = {function.key for function in self._functions}

    def all(self) -> list[FunctionDefinition]:
        return list(self._functions)

    def has(self, key: str) -> bool:
        return key in self._keys


@dataclass(frozen=True)
class RuntimeSnapshot:
    program_enabled: bool
    dry_run: bool
    auto_answer_enabled: bool
    send_delay_seconds: float
    send_delay_min_seconds: float
    send_delay_max_seconds: float
    latest_question: str | None
    functions: dict[str, bool]


class RuntimeControls:
    def __init__(
        self,
        base_config: BotConfig,
        registry: FunctionRegistry | None = None,
        *,
        program_enabled: bool = True,
    ) -> None:
        self._base_config = base_config
        self.registry = registry or default_function_registry()
        self._lock = RLock()
        self._program_enabled = program_enabled and base_config.program_enabled
        self._dry_run = base_config.dry_run
        self._auto_answer_enabled = base_config.auto_answer_enabled
        self._send_delay_seconds = base_config.send_delay_seconds
        self._send_delay_min_seconds = base_config.send_delay_min_seconds
        self._send_delay_max_seconds = base_config.send_delay_max_seconds
        self._latest_question: str | None = None
        self._functions = {
            function.key: function.enabled_by_default
            for function in self.registry.all()
        }
        if self.registry.has(FIND_ANSWER_FUNCTION):
            self._functions[FIND_ANSWER_FUNCTION] = self._auto_answer_enabled

    @classmethod
    def from_config(
        cls,
        config: BotConfig,
        registry: FunctionRegistry | None = None,
    ) -> RuntimeControls:
        return cls(config, registry=registry)

    def get_config(self) -> BotConfig:
        with self._lock:
            return replace(
                self._base_config,
                program_enabled=self._program_enabled,
                auto_answer_enabled=self._auto_answer_enabled,
                dry_run=self._dry_run,
                send_delay_seconds=self._send_delay_seconds,
                send_delay_min_seconds=self._send_delay_min_seconds,
                send_delay_max_seconds=self._send_delay_max_seconds,
            )

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return RuntimeSnapshot(
                program_enabled=self._program_enabled,
                dry_run=self._dry_run,
                auto_answer_enabled=self._auto_answer_enabled,
                send_delay_seconds=self._send_delay_seconds,
                send_delay_min_seconds=self._send_delay_min_seconds,
                send_delay_max_seconds=self._send_delay_max_seconds,
                latest_question=self._latest_question,
                functions=dict(self._functions),
            )

    def is_program_enabled(self) -> bool:
        with self._lock:
            return self._program_enabled

    def set_program_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._program_enabled = enabled

    def set_dry_run(self, enabled: bool) -> None:
        with self._lock:
            self._dry_run = enabled

    def get_latest_question(self) -> str | None:
        with self._lock:
            return self._latest_question

    def set_latest_question(self, question: str | None) -> None:
        clean_question = question.strip() if question else ""
        with self._lock:
            self._latest_question = clean_question or None

    def set_auto_answer_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._auto_answer_enabled = enabled
            if self.registry.has(FIND_ANSWER_FUNCTION):
                self._functions[FIND_ANSWER_FUNCTION] = enabled

    def set_send_delay_seconds(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("send_delay_seconds must be 0 or greater.")
        with self._lock:
            self._send_delay_seconds = seconds
            self._send_delay_min_seconds = seconds
            self._send_delay_max_seconds = seconds

    def set_send_delay_range(self, min_seconds: float, max_seconds: float) -> None:
        if min_seconds < 0 or max_seconds < 0:
            raise ValueError("send_delay_seconds must be 0 or greater.")
        if min_seconds > max_seconds:
            raise ValueError(
                "Minimum send delay must be less than or equal to maximum send delay."
            )
        with self._lock:
            self._send_delay_seconds = min_seconds
            self._send_delay_min_seconds = min_seconds
            self._send_delay_max_seconds = max_seconds

    def is_function_enabled(self, key: str) -> bool:
        with self._lock:
            self._require_function(key)
            return self._functions[key]

    def set_function_enabled(self, key: str, enabled: bool) -> None:
        with self._lock:
            self._require_function(key)
            self._functions[key] = enabled
            if key == FIND_ANSWER_FUNCTION:
                self._auto_answer_enabled = enabled

    def _require_function(self, key: str) -> None:
        if not self.registry.has(key):
            raise KeyError(f"Unknown function: {key}")


def default_function_registry() -> FunctionRegistry:
    return FunctionRegistry(
        [
            FunctionDefinition(
                key=FIND_ANSWER_FUNCTION,
                label="Find answer",
                enabled_by_default=True,
            ),
            FunctionDefinition(
                key=SCREEN_PHRASE_WATCHER_FUNCTION,
                label="Screen phrase watcher",
                enabled_by_default=False,
            )
        ]
    )
