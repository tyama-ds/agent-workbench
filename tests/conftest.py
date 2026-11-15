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
