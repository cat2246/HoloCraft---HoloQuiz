from __future__ import annotations

from dataclasses import dataclass, replace
from threading import RLock

from holoquiz.config import (
    BotConfig,
    ChatTriggerConfig,
    CoordinateLockConfig,
    validate_coordinate_lock_look_mode,
)


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
    chat_triggers: tuple[ChatTriggerConfig, ...]
    chat_trigger_dry_run: bool
    coordinate_lock_enabled: bool
    coordinate_lock_auto_hit_enabled: bool
    coordinate_lock_auto_hit_min_seconds: float
    coordinate_lock_auto_hit_max_seconds: float
    coordinate_lock_look_mode: str
    coordinate_locks: tuple[CoordinateLockConfig, ...]


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
        self._chat_triggers = tuple(base_config.chat_triggers)
        self._chat_trigger_dry_run = base_config.chat_trigger_dry_run
        self._coordinate_lock_enabled = base_config.coordinate_lock_enabled
        self._coordinate_lock_auto_hit_enabled = (
            base_config.coordinate_lock_auto_hit_enabled
        )
        self._coordinate_lock_auto_hit_min_seconds = (
            base_config.coordinate_lock_auto_hit_min_seconds
        )
        self._coordinate_lock_auto_hit_max_seconds = (
            base_config.coordinate_lock_auto_hit_max_seconds
        )
        self._coordinate_lock_look_mode = validate_coordinate_lock_look_mode(
            base_config.coordinate_lock_look_mode
        )
        self._coordinate_locks = _only_first_coordinate_lock_enabled(
            base_config.coordinate_locks
        )
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
                chat_triggers=tuple(self._chat_triggers),
                chat_trigger_dry_run=self._chat_trigger_dry_run,
                coordinate_lock_enabled=self._coordinate_lock_enabled,
                coordinate_lock_auto_hit_enabled=self._coordinate_lock_auto_hit_enabled,
                coordinate_lock_auto_hit_min_seconds=(
                    self._coordinate_lock_auto_hit_min_seconds
                ),
                coordinate_lock_auto_hit_max_seconds=(
                    self._coordinate_lock_auto_hit_max_seconds
                ),
                coordinate_lock_look_mode=self._coordinate_lock_look_mode,
                coordinate_locks=tuple(self._coordinate_locks),
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
                chat_triggers=tuple(self._chat_triggers),
                chat_trigger_dry_run=self._chat_trigger_dry_run,
                coordinate_lock_enabled=self._coordinate_lock_enabled,
                coordinate_lock_auto_hit_enabled=self._coordinate_lock_auto_hit_enabled,
                coordinate_lock_auto_hit_min_seconds=(
                    self._coordinate_lock_auto_hit_min_seconds
                ),
                coordinate_lock_auto_hit_max_seconds=(
                    self._coordinate_lock_auto_hit_max_seconds
                ),
                coordinate_lock_look_mode=self._coordinate_lock_look_mode,
                coordinate_locks=tuple(self._coordinate_locks),
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

    def get_chat_triggers(self) -> tuple[ChatTriggerConfig, ...]:
        with self._lock:
            return tuple(self._chat_triggers)

    def set_chat_triggers(
        self,
        triggers: list[ChatTriggerConfig] | tuple[ChatTriggerConfig, ...],
    ) -> None:
        with self._lock:
            self._chat_triggers = tuple(triggers)

    def set_chat_trigger_dry_run(self, enabled: bool) -> None:
        with self._lock:
            self._chat_trigger_dry_run = enabled

    def is_coordinate_lock_enabled(self) -> bool:
        with self._lock:
            return self._coordinate_lock_enabled

    def set_coordinate_lock_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._coordinate_lock_enabled = enabled

    def set_coordinate_lock_auto_hit_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._coordinate_lock_auto_hit_enabled = enabled

    def set_coordinate_lock_auto_hit_range(
        self,
        min_seconds: float,
        max_seconds: float,
    ) -> None:
        if min_seconds <= 0 or max_seconds <= 0:
            raise ValueError("Auto hit times must be greater than 0.")
        if min_seconds > max_seconds:
            raise ValueError(
                "Minimum auto hit time must be less than or equal to maximum time."
            )
        with self._lock:
            self._coordinate_lock_auto_hit_min_seconds = min_seconds
            self._coordinate_lock_auto_hit_max_seconds = max_seconds

    def set_coordinate_lock_look_mode(self, mode: str) -> None:
        validated = validate_coordinate_lock_look_mode(mode)
        with self._lock:
            self._coordinate_lock_look_mode = validated

    def get_coordinate_locks(self) -> tuple[CoordinateLockConfig, ...]:
        with self._lock:
            return tuple(self._coordinate_locks)

    def set_coordinate_locks(
        self,
        locks: list[CoordinateLockConfig] | tuple[CoordinateLockConfig, ...],
    ) -> None:
        with self._lock:
            self._coordinate_locks = _only_first_coordinate_lock_enabled(locks)

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


def _only_first_coordinate_lock_enabled(
    locks: list[CoordinateLockConfig] | tuple[CoordinateLockConfig, ...],
) -> tuple[CoordinateLockConfig, ...]:
    found_enabled = False
    normalized: list[CoordinateLockConfig] = []
    for lock in locks:
        if lock.enabled and found_enabled:
            normalized.append(replace(lock, enabled=False))
            continue
        normalized.append(lock)
        if lock.enabled:
            found_enabled = True
    return tuple(normalized)
