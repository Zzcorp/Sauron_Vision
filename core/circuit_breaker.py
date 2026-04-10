"""
Sauron Vision — Circuit Breaker pattern for external API calls.

Tracks failures per service and prevents cascading failures by
blocking calls to unhealthy services until they recover.

States
------
CLOSED    Normal operation. Failures are counted.
OPEN      Service is considered unhealthy. All calls are blocked.
HALF_OPEN One probe call is allowed to test recovery.

Usage
-----
As a decorator::

    from core.circuit_breaker import circuit_breaker

    @circuit_breaker("fmp")
    def fetch_fmp_data():
        ...

As a context manager::

    from core.circuit_breaker import CircuitBreaker

    with CircuitBreaker.get("fmp"):
        ...

Query all breakers (e.g., for a dashboard)::

    from core.circuit_breaker import CircuitBreaker
    states = CircuitBreaker.get_all_states()
"""
import functools
import logging
import threading
import time
from contextlib import contextmanager
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("core.circuit_breaker")

# ─────────────────────────────────────────────────────────────────────────────
# State enum
# ─────────────────────────────────────────────────────────────────────────────

class State(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


# ─────────────────────────────────────────────────────────────────────────────
# Exception raised when a call is blocked by an open breaker
# ─────────────────────────────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when a call is blocked because the circuit breaker is OPEN."""

    def __init__(self, service: str):
        self.service = service
        super().__init__(
            f"Circuit breaker for '{service}' is OPEN — calls are blocked until recovery."
        )


# ─────────────────────────────────────────────────────────────────────────────
# Core class
# ─────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Thread-safe circuit breaker for a single named service.

    Parameters
    ----------
    service:
        Logical name of the service being protected (e.g. "fmp").
    failure_threshold:
        Number of consecutive failures that trip the breaker to OPEN.
    recovery_timeout:
        Seconds to wait in OPEN state before moving to HALF_OPEN.
    """

    # Module-level registry: service_name -> CircuitBreaker instance
    _registry: Dict[str, "CircuitBreaker"] = {}
    _registry_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ init

    def __init__(
        self,
        service: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 300.0,
    ) -> None:
        self.service = service
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state: State = State.CLOSED
        self._failure_count: int = 0
        self._opened_at: Optional[float] = None
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ registry helpers

    @classmethod
    def get(
        cls,
        service: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 300.0,
    ) -> "CircuitBreaker":
        """Return (or create) the breaker for *service* from the registry."""
        with cls._registry_lock:
            if service not in cls._registry:
                cls._registry[service] = cls(
                    service,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                )
            return cls._registry[service]

    @classmethod
    def get_all_states(cls) -> Dict[str, Dict[str, Any]]:
        """
        Return a snapshot of every registered breaker's status.

        Suitable for a health / dashboard endpoint.

        Returns
        -------
        dict keyed by service name, each value a dict with keys:
            state, failure_count, failure_threshold, recovery_timeout,
            opened_at, seconds_until_retry
        """
        with cls._registry_lock:
            snapshot = {}
            now = time.monotonic()
            for name, breaker in cls._registry.items():
                with breaker._lock:
                    seconds_until_retry: Optional[float] = None
                    if breaker._state is State.OPEN and breaker._opened_at is not None:
                        remaining = breaker.recovery_timeout - (now - breaker._opened_at)
                        seconds_until_retry = max(0.0, remaining)

                    snapshot[name] = {
                        "state": breaker._state.value,
                        "failure_count": breaker._failure_count,
                        "failure_threshold": breaker.failure_threshold,
                        "recovery_timeout": breaker.recovery_timeout,
                        "opened_at": breaker._opened_at,
                        "seconds_until_retry": seconds_until_retry,
                    }
            return snapshot

    # ------------------------------------------------------------------ state transitions

    def _transition(self, new_state: State) -> None:
        """Perform a state transition and log it. Must be called under self._lock."""
        old_state = self._state
        self._state = new_state
        if new_state is State.OPEN:
            self._opened_at = time.monotonic()
        elif new_state is State.CLOSED:
            self._failure_count = 0
            self._opened_at = None
        logger.warning(
            "[CircuitBreaker] '%s' transitioned %s -> %s",
            self.service,
            old_state.value,
            new_state.value,
        )

    # ------------------------------------------------------------------ call guard

    def _before_call(self) -> None:
        """
        Check whether a call should be allowed.

        Raises CircuitOpenError if the breaker is OPEN and the recovery
        timeout has not yet elapsed.  Transitions to HALF_OPEN when the
        timeout has elapsed.
        """
        with self._lock:
            if self._state is State.CLOSED:
                return

            if self._state is State.HALF_OPEN:
                # Only one probe at a time — block further calls until the
                # probe succeeds or fails.
                raise CircuitOpenError(self.service)

            # OPEN — check timeout
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed >= self.recovery_timeout:
                    self._transition(State.HALF_OPEN)
                    return  # Allow the probe call through
            raise CircuitOpenError(self.service)

    def _on_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state is State.HALF_OPEN:
                self._transition(State.CLOSED)
                logger.info(
                    "[CircuitBreaker] '%s' recovered — circuit CLOSED.", self.service
                )
            elif self._state is State.CLOSED:
                # Reset consecutive failure count on any success
                self._failure_count = 0

    def _on_failure(self, exc: BaseException) -> None:
        """Record a failed call and open the circuit if threshold is reached."""
        with self._lock:
            if self._state is State.HALF_OPEN:
                # Probe failed — go back to OPEN
                self._transition(State.OPEN)
                logger.error(
                    "[CircuitBreaker] '%s' probe failed (%s) — back to OPEN.",
                    self.service,
                    type(exc).__name__,
                )
                return

            if self._state is State.CLOSED:
                self._failure_count += 1
                logger.debug(
                    "[CircuitBreaker] '%s' failure %d/%d: %s",
                    self.service,
                    self._failure_count,
                    self.failure_threshold,
                    type(exc).__name__,
                )
                if self._failure_count >= self.failure_threshold:
                    self._transition(State.OPEN)
                    logger.error(
                        "[CircuitBreaker] '%s' failure threshold reached — circuit OPEN.",
                        self.service,
                    )

    # ------------------------------------------------------------------ context manager

    @contextmanager
    def __call__(self):
        """Allow the breaker instance to be used as a context manager."""
        self._before_call()
        try:
            yield self
        except Exception as exc:
            self._on_failure(exc)
            raise
        else:
            self._on_success()

    # ------------------------------------------------------------------ decorator support

    def decorate(self, func: Callable) -> Callable:
        """Wrap *func* so every call is guarded by this circuit breaker."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            self._before_call()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                self._on_failure(exc)
                raise
            else:
                self._on_success()
                return result
        return wrapper

    def __repr__(self) -> str:
        return (
            f"CircuitBreaker(service={self.service!r}, state={self._state.value}, "
            f"failures={self._failure_count}/{self.failure_threshold})"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Convenience decorator factory
# ─────────────────────────────────────────────────────────────────────────────

def circuit_breaker(
    service: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 300.0,
) -> Callable:
    """
    Decorator factory that guards a function with a named circuit breaker.

    The breaker is retrieved from (or added to) the module-level registry,
    so all decorated functions sharing the same *service* name share one
    breaker instance.

    Example
    -------
    ::

        @circuit_breaker("fmp")
        def fetch_fmp_data():
            ...

        @circuit_breaker("twelve_data", failure_threshold=3, recovery_timeout=120)
        def fetch_twelve_data():
            ...
    """
    breaker = CircuitBreaker.get(
        service,
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
    )
    return breaker.decorate
