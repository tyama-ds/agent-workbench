"""Optional, request-local observations with no provider inputs or authority.

``with observe_provider(callback): await client.complete(...)`` leaves provider
signatures unchanged. Callbacks are synchronous and receive detached snapshots;
their failures never change requests, cancellation, retry policy or return values.
Times measure adapter boundaries, not exact socket starts or GPU-only wait time.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import inspect
import math
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar


_OBSERVER = ContextVar('workbench_provider_observer', default=None)
_CALL = ContextVar('workbench_provider_observation_call', default=None)
_PHASES = frozenset({'queue_wait', 'admitted', 'response_wait', 'received', 'parse',
                     'completed', 'error', 'cancelled', 'retry_wait'})
_USAGE_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens', 'prompt_tokens',
                 'completion_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens')
_USAGE_DETAILS = {'prompt_tokens_details': ('cached_tokens', 'audio_tokens'),
                  'completion_tokens_details': ('reasoning_tokens', 'audio_tokens',
                                               'accepted_prediction_tokens', 'rejected_prediction_tokens')}


@contextmanager
def observe_provider(callback):
    """Install a task-local synchronous sink, or None to suppress a nested scope."""
    if callback is not None and (not callable(callback) or inspect.iscoroutinefunction(callback)):
        raise TypeError('Provider observer must be a synchronous callable or None')
    token = _OBSERVER.set(callback)
    try:
        yield
    finally:
        _OBSERVER.reset(token)


def _seconds(value):
    return float(value) if type(value) in (int, float) and 0 <= value <= 86400 and math.isfinite(value) else None


def _usage(value):
    if type(value) is not dict:
        return {}
    count = lambda item: type(item) is int and 0 <= item <= 9007199254740991
    result = {key: value[key] for key in _USAGE_FIELDS if count(value.get(key))}
    for key, fields in _USAGE_DETAILS.items():
        detail = value.get(key)
        if type(detail) is dict:
            clean = {name: detail[name] for name in fields if count(detail.get(name))}
            if clean:
                result[key] = clean
    return result


def _error_type(error):
    names = {kind.__name__ for kind in type(error).__mro__}
    for name, code in (('CancelledError', 'cancelled'),
                       ('ProviderTimeoutError', 'provider_timeout'),
                       ('ProviderOutputLimitError', 'provider_output_limit'),
                       ('ResourceError', 'resource_error'), ('ProviderError', 'provider_error'),
                       ('ValueError', 'validation_error'), ('TypeError', 'validation_error')):
        if name in names:
            return code
    return 'unexpected_error'


class _Observation:
    def __init__(self, callback):
        self.callback = callback
        self.call_id = 'provider-' + secrets.token_hex(12)
        self.started = time.monotonic()
        self.phase_started = self.started
        self.phase_started_at = time.time()
        self.phase = None
        self.sequence = 0
        self.attempt = self.attempt_limit = 1
        self.provider_kind = 'unknown'
        self.admission_kind = 'none'
        self.request_timeout = self.queue_timeout = None
        self.callback_failures = 0
        self.emitting = False

    def configure(self, *, provider_kind, admission_kind, request_timeout_seconds,
                  queue_timeout_seconds=None, attempt_limit=1):
        if self.emitting:
            return
        self.provider_kind = provider_kind if provider_kind in ('local', 'openai', 'anthropic') else 'unknown'
        self.admission_kind = admission_kind if admission_kind in ('local', 'copilot', 'none') else 'none'
        self.request_timeout = _seconds(request_timeout_seconds)
        self.queue_timeout = _seconds(queue_timeout_seconds)
        self.attempt_limit = attempt_limit if type(attempt_limit) is int and 1 <= attempt_limit <= 4 else 1

    def emit(self, phase, *, attempt=None, terminal=False, retry_after_seconds=None, error=None, usage=None):
        if self.emitting or phase not in _PHASES:
            return
        now, wall = time.monotonic(), time.time()
        previous, previous_elapsed = self.phase, max(0.0, now - self.phase_started)
        if attempt is not None and type(attempt) is int and 1 <= attempt <= self.attempt_limit:
            self.attempt = attempt
        self.phase, self.phase_started, self.phase_started_at = phase, now, wall
        self.sequence += 1
        value = {'schema_version': 1, 'call_id': self.call_id, 'sequence': self.sequence,
                 'provider_kind': self.provider_kind, 'admission_kind': self.admission_kind,
                 'phase': phase, 'terminal': terminal is True,
                 'attempt': self.attempt, 'attempt_limit': self.attempt_limit,
                 'observed_at': wall, 'phase_started_at': self.phase_started_at,
                 'elapsed_seconds': max(0.0, now - self.started), 'phase_elapsed_seconds': 0.0,
                 'request_timeout_seconds': self.request_timeout, 'queue_timeout_seconds': self.queue_timeout,
                 'observer_callback_failures': self.callback_failures}
        if previous is not None:
            value.update(previous_phase=previous, previous_phase_elapsed_seconds=previous_elapsed)
        if retry_after_seconds is not None:
            value['retry_after_seconds'] = _seconds(retry_after_seconds)
        if error is not None:
            value['error_type'] = _error_type(error)
        if usage is not None:
            value['usage'] = _usage(usage)
        # Retain no mutable event object: changing a callback's copy cannot
        # rewrite another observation or provider retry/timeout configuration.
        self.emitting = True
        try:
            returned = self.callback(copy.deepcopy(value))
            if inspect.iscoroutine(returned):
                returned.close()  # An accidentally returned coroutine is never awaited.
                self.callback_failures += 1
        except BaseException:
            self.callback_failures += 1
        finally:
            self.emitting = False


def configure_observation(**fields):
    current = _CALL.get()
    if current is not None:
        current.configure(**fields)


def observation_phase(phase, **fields):
    current = _CALL.get()
    if current is not None:
        current.emit(phase, **fields)


def observed_provider_call(function):
    """One isolated observation per complete call, including errors/cancellation."""
    @functools.wraps(function)
    async def wrapped(*args, **kwargs):
        callback = _OBSERVER.get()
        current = _Observation(callback) if callback is not None else None
        token = _CALL.set(current)
        try:
            try:
                result = await function(*args, **kwargs)
            except asyncio.CancelledError as error:
                if current is not None:
                    current.emit('cancelled', terminal=True, error=error)
                raise
            except BaseException as error:
                if current is not None:
                    current.emit('error', terminal=True, error=error)
                raise
            if current is not None:
                current.emit('completed', terminal=True, usage=getattr(result, 'usage', None))
            return result
        finally:
            _CALL.reset(token)
    return wrapped
