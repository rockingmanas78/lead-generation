from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

@dataclass
class CredentialHealthState:
    is_permanently_disabled: bool = False
    cooldown_until_epoch_seconds: float = 0.0
    consecutive_failures: int = 0
    last_error_message: Optional[str] = None

    def is_available_now(self) -> bool:
        if self.is_permanently_disabled:
            return False
        return time.time() >= self.cooldown_until_epoch_seconds

class RotatingCredentialPool:
    """Generic round-robin pool with cooldown + permanent disable."""

    def __init__(self, number_of_credentials: int) -> None:
        self._states: List[CredentialHealthState] = [CredentialHealthState() for _ in range(number_of_credentials)]
        self._current_index: int = 0

    def any_available(self) -> bool:
        return any(state.is_available_now() for state in self._states)

    def acquire_next_available_index(self) -> Optional[int]:
        if not self._states:
            return None

        starting_index = self._current_index
        for _ in range(len(self._states)):
            state = self._states[self._current_index]
            if state.is_available_now():
                return self._current_index
            self._current_index = (self._current_index + 1) % len(self._states)

        # restore to starting index for predictability
        self._current_index = starting_index
        return None

    def mark_success(self, credential_index: int) -> None:
        state = self._states[credential_index]
        state.consecutive_failures = 0
        state.last_error_message = None

        # move pointer forward for basic round robin fairness
        self._current_index = (credential_index + 1) % len(self._states)

    def mark_transient_failure_with_cooldown(self, credential_index: int, cooldown_seconds: float, error_message: str) -> None:
        state = self._states[credential_index]
        state.consecutive_failures += 1
        state.last_error_message = error_message
        state.cooldown_until_epoch_seconds = max(state.cooldown_until_epoch_seconds, time.time() + cooldown_seconds)
        self._current_index = (credential_index + 1) % len(self._states)

    def mark_permanent_failure(self, credential_index: int, error_message: str) -> None:
        state = self._states[credential_index]
        state.is_permanently_disabled = True
        state.last_error_message = error_message
        self._current_index = (credential_index + 1) % len(self._states)

class GoogleCustomSearchCredentialPool:
    """Rotates (api_key, search_engine_id) pairs."""

    def __init__(self, credential_pairs: List[Tuple[str, str]]) -> None:
        self.credential_pairs = credential_pairs
        self.pool = RotatingCredentialPool(len(credential_pairs))

    def acquire(self) -> Optional[Tuple[int, str, str]]:
        index = self.pool.acquire_next_available_index()
        if index is None:
            return None
        api_key, search_engine_identifier = self.credential_pairs[index]
        return index, api_key, search_engine_identifier

    def success(self, index: int) -> None:
        self.pool.mark_success(index)

    def cooldown(self, index: int, cooldown_seconds: float, error_message: str) -> None:
        self.pool.mark_transient_failure_with_cooldown(index, cooldown_seconds, error_message)

    def disable(self, index: int, error_message: str) -> None:
        self.pool.mark_permanent_failure(index, error_message)

    def has_any_available(self) -> bool:
        return self.pool.any_available()

class ZeroBounceApiKeyPool:
    """Rotates ZeroBounce API keys."""

    def __init__(self, api_keys: List[str]) -> None:
        self.api_keys = api_keys
        self.pool = RotatingCredentialPool(len(api_keys))

    def acquire(self) -> Optional[Tuple[int, str]]:
        index = self.pool.acquire_next_available_index()
        if index is None:
            return None
        return index, self.api_keys[index]

    def success(self, index: int) -> None:
        self.pool.mark_success(index)

    def cooldown(self, index: int, cooldown_seconds: float, error_message: str) -> None:
        self.pool.mark_transient_failure_with_cooldown(index, cooldown_seconds, error_message)

    def disable(self, index: int, error_message: str) -> None:
        self.pool.mark_permanent_failure(index, error_message)

    def has_any_available(self) -> bool:
        return self.pool.any_available()
