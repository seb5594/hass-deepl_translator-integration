"""Test setup that is not specific to one test."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _start_dns_helper_thread_early():
    """pycares 5 starts one background thread for the whole process when the first resolver
    appears. Home Assistant releases from before it existed count such a thread as left over by
    whichever test happens to create it, so create it before any test is measured."""
    try:
        import pycares

        pycares.Channel()
    except Exception:  # noqa: BLE001 - older pycares releases need no warm-up
        pass

