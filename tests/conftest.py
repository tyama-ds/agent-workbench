"""Shared test defaults.

Phase 7 asks the human before Python, browser and overwrite operations by
default. Most tests exercise those tools directly without a person, so they
run with approvals off; tests marked `approvals` keep the shipped default.
"""
import pytest

import workbench.config as workbench_config


def pytest_configure(config):
    config.addinivalue_line('markers', 'approvals: keep the default approval mode (ask)')
    config.addinivalue_line('markers', 'plan: keep the mandatory plan_work gate for root PMs')
    config.addinivalue_line('markers', 'question_limits: keep the limit on questions that wait for a person')
    config.addinivalue_line('markers', 'stall: keep the wake-up of a team in which everybody waits')
    config.addinivalue_line('markers', 'review: keep the reviewer that reads the saved files before completion')
    config.addinivalue_line('markers', 'persona: keep the manner of speaking that goes with an agent\'s face')


@pytest.fixture(autouse=True)
def _approvals_off_unless_marked(request):
    # Not monkeypatch: sharing the test's monkeypatch instance would change
    # the order in which other fixtures' patches are undone.
    settings = workbench_config.DEFAULT['approvals']
    previous = settings['mode']
    if request.node.get_closest_marker('approvals') is None:
        settings['mode'] = 'always_allow'
    yield
    settings['mode'] = previous


@pytest.fixture(autouse=True)
def _plan_not_required_unless_marked(request):
    """Phase 8 makes plan_work mandatory for root PMs. Existing tests script
    PMs that call tools directly, so they run without the gate; tests marked
    `plan` keep the shipped behaviour."""
    from workbench.engine import Engine
    previous = Engine.plan_required
    Engine.plan_required = request.node.get_closest_marker('plan') is not None
    yield
    Engine.plan_required = previous


@pytest.fixture(autouse=True)
def _unlimited_human_questions_unless_marked(request):
    """Phase 9 limits questions that wait for a person (root PM only, twice per
    run). Existing tests script workers that ask freely; tests marked
    `question_limits` keep the shipped behaviour."""
    from workbench.engine import Engine
    previous = Engine.human_question_limit
    Engine.human_question_limit = 2 if request.node.get_closest_marker('question_limits') is not None else None
    yield
    Engine.human_question_limit = previous


@pytest.fixture(autouse=True)
def _no_stall_recovery_unless_marked(request):
    """The application wakes a PM when the whole team only waits. Existing
    tests park agents on purpose to inspect that state; tests marked `stall`
    keep the shipped behaviour."""
    from workbench.engine import Engine
    previous = Engine.stall_recovery
    Engine.stall_recovery = request.node.get_closest_marker('stall') is not None
    yield
    Engine.stall_recovery = previous


@pytest.fixture(autouse=True)
def _fresh_search_guard():
    """The DuckDuckGo pacing and block memory is process-wide; tests start
    unblocked and without the two-second spacing."""
    from workbench.webtools import BRAVE_PACE, SEARCH_GUARD
    SEARCH_GUARD.reset()
    SEARCH_GUARD.min_interval = 0.0
    BRAVE_PACE.reset()
    BRAVE_PACE.min_interval = 0.0
    yield
    SEARCH_GUARD.reset()
    SEARCH_GUARD.min_interval = 2.0
    BRAVE_PACE.reset()
    BRAVE_PACE.min_interval = 1.1


@pytest.fixture(autouse=True)
def _no_review_before_completion_unless_marked(request):
    """A reviewer reads the saved files before the coordinator finishes (the shipped default). Existing tests
    script every agent of a run, so they run without it; tests marked `review` keep the shipped behaviour."""
    from workbench.engine import Engine
    previous = Engine.review_default
    Engine.review_default = request.node.get_closest_marker('review') is not None
    yield
    Engine.review_default = previous


@pytest.fixture(autouse=True)
def _no_manner_of_speaking_unless_marked(request):
    """Agents are told to speak like the face the screen gives them (the shipped default). That adds a paragraph
    to every agent's instructions; existing tests compare or script those, so they run without it. Tests marked
    `persona` keep the shipped behaviour."""
    from workbench.engine import Engine
    previous = Engine.persona_default
    Engine.persona_default = request.node.get_closest_marker('persona') is not None
    yield
    Engine.persona_default = previous
