"""Resilience decorators for ARM transports (cloud design patterns: Retry, Circuit Breaker).

Both wrap any ``ArmTransport`` (Decorator pattern) and can be stacked:
``RetryingTransport(CircuitBreakerTransport(transport))`` retries transient faults with
exponential backoff and stops as soon as the circuit is open.

* Only transient faults (HTTP 408/429/5xx) are retried or counted by the breaker.
* Non-idempotent POST actions (ingest a report, add an annotation) are retried only on
  429, when ARM rejected the call before running it. Read-only POSTs (Resource Graph
  queries, history actions) are always safe to retry.
* The circuit breaker is a State machine: closed -> open -> half-open -> closed/open.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..client import HealthModelError

TRANSIENT_STATUS = frozenset({408, 429, 500, 502, 503, 504})
TRANSIENT_CODES = frozenset({"TooManyRequests", "ServerBusy", "ServiceUnavailable", "InternalServerError",
                             "GatewayTimeout", "BadGateway", "RequestTimeout", "ServerTimeout"})
READ_ONLY_POST_SUFFIXES = ("/providers/Microsoft.ResourceGraph/resources", "/getHistory", "/getSignalHistory",
                           "/getDataAnnotations", "/getSignalRecommendations")
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def is_transient(error: BaseException) -> bool:
    return isinstance(error, HealthModelError) and not isinstance(error, CircuitOpenError) and (
        error.status in TRANSIENT_STATUS or error.code in TRANSIENT_CODES)


def is_throttled(error: BaseException) -> bool:
    return isinstance(error, HealthModelError) and (error.status == 429 or error.code == "TooManyRequests")


def is_read_only_call(method: str, url: str) -> bool:
    method = method.upper()
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    return method == "POST" and urlsplit(url).path.endswith(READ_ONLY_POST_SUFFIXES)


def is_idempotent(method: str, url: str) -> bool:
    return method.upper() in IDEMPOTENT_METHODS or is_read_only_call(method, url)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 4
    base_delay: float = 2.0
    max_delay: float = 30.0
    jitter: float = 0.25  # fraction of the delay, randomised to avoid synchronised retries

    def delay(self, retry: int, rng=random.random) -> float:
        delay = min(self.max_delay, self.base_delay * (2 ** retry))
        return delay + delay * self.jitter * rng() if self.jitter else delay


class RetryingTransport:
    def __init__(self, inner, policy: RetryPolicy | None = None, sleep=time.sleep, rng=random.random):
        self.inner = inner
        self.policy = policy or RetryPolicy()
        self._sleep, self._rng = sleep, rng

    def request(self, method: str, url: str, body: dict | None = None):
        idempotent = is_idempotent(method, url)
        for attempt in range(self.policy.attempts):
            try:
                return self.inner.request(method, url, body)
            except HealthModelError as error:
                retryable = is_transient(error) and (idempotent or is_throttled(error))
                if not retryable or attempt == self.policy.attempts - 1:
                    raise
                self._sleep(self.policy.delay(attempt, self._rng))
        raise AssertionError("unreachable")


class CircuitOpenError(HealthModelError):
    def __init__(self, retry_in: float):
        super().__init__(f"Azure Resource Manager calls are paused for {retry_in:.0f}s after repeated transient "
                         "failures (circuit open). Retry later.", "CircuitOpen", None)


class _State:
    name = "abstract"

    def before_call(self, breaker: "CircuitBreakerTransport") -> None: ...

    def on_success(self, breaker: "CircuitBreakerTransport") -> None:
        breaker._transition(_Closed())

    def on_failure(self, breaker: "CircuitBreakerTransport") -> None: ...


class _Closed(_State):
    name = "closed"

    def __init__(self):
        self.failures = 0

    def on_failure(self, breaker):
        self.failures += 1
        if self.failures >= breaker.failure_threshold:
            breaker._transition(_Open(breaker.clock()))


class _Open(_State):
    name = "open"

    def __init__(self, opened_at: float):
        self.opened_at = opened_at

    def before_call(self, breaker):
        elapsed = breaker.clock() - self.opened_at
        if elapsed < breaker.reset_timeout:
            raise CircuitOpenError(breaker.reset_timeout - elapsed)
        breaker._transition(_HalfOpen())
        breaker._state.before_call(breaker)


class _HalfOpen(_State):
    """One trial call decides: success closes the circuit, a transient failure re-opens it."""

    name = "half-open"

    def __init__(self):
        self.trial_running = False

    def before_call(self, breaker):
        if self.trial_running:
            raise CircuitOpenError(0)
        self.trial_running = True

    def on_failure(self, breaker):
        breaker._transition(_Open(breaker.clock()))


class CircuitBreakerTransport:
    def __init__(self, inner, failure_threshold: int = 5, reset_timeout: float = 30.0, clock=time.monotonic):
        self.inner = inner
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.clock = clock
        self._state: _State = _Closed()
        self._lock = threading.RLock()

    @property
    def state_name(self) -> str:
        return self._state.name

    def _transition(self, state: _State) -> None:
        self._state = state

    def request(self, method: str, url: str, body: dict | None = None):
        with self._lock:
            self._state.before_call(self)
        try:
            result = self.inner.request(method, url, body)
        except Exception as error:
            with self._lock:
                if is_transient(error):
                    self._state.on_failure(self)
                else:
                    self._record_success()  # Azure answered (for example 404): the dependency is reachable.
            raise
        with self._lock:
            self._record_success()
        return result

    def _record_success(self) -> None:
        if not isinstance(self._state, _Closed) or self._state.failures:
            self._state.on_success(self)
