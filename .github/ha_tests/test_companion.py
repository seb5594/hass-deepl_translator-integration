"""Optional companion discovery through real Home Assistant lifecycle signals."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.helpers.dispatcher import async_dispatcher_send

try:
    from pytest_homeassistant.common import MockConfigEntry
except ImportError:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.deepl_translator.companion import (
    TRANSLATOR,
    async_watch_translator,
)

MODULE = "custom_components.deepl_translator.companion"


@pytest.fixture
def companion(hass):
    cleanups = []
    entry = SimpleNamespace(async_on_unload=cleanups.append)
    installed = {TRANSLATOR: SimpleNamespace(config_flow=True, version="2026.11.05.3")}
    with (
        patch(f"{MODULE}.MAJOR_VERSION", 2026),
        patch(f"{MODULE}.MINOR_VERSION", 11),
        patch(
            f"{MODULE}.async_get_custom_components",
            new=AsyncMock(return_value=installed),
        ) as scan,
        patch(f"{MODULE}.discovery_flow.async_create_flow") as create,
    ):
        yield entry, cleanups, installed, scan, create
    for cleanup in reversed(cleanups):
        cleanup()


async def test_startup_and_installer_events(hass, companion):
    entry, cleanups, _installed, scan, create = companion
    async_watch_translator(hass, entry)
    await hass.async_block_till_done()
    create.assert_called_once_with(
        hass, TRANSLATOR, {"source": "integration_discovery"}, {}
    )
    create.reset_mock()
    scan.reset_mock()
    for signal, payload in (
        ("hacs_dispatch_repository", {"action": "update"}),
        ("hacs_dispatch_repository", {"action": "uninstall"}),
        ("marketplace_repository_install_progress", {"progress": 0}),
        ("marketplace_repository_install_progress", {"progress": 90}),
    ):
        async_dispatcher_send(hass, signal, payload)
    await hass.async_block_till_done()
    scan.assert_not_called()
    for signal, payload in (
        ("hacs_dispatch_repository", {"action": "install"}),
        ("marketplace_repository_install_progress", {"progress": False}),
    ):
        async_dispatcher_send(hass, signal, payload)
        await hass.async_block_till_done()
        create.assert_called_once()
        create.reset_mock()
    for cleanup in reversed(cleanups):
        cleanup()
    cleanups.clear()
    async_dispatcher_send(hass, "hacs_dispatch_repository", {"action": "install"})
    await hass.async_block_till_done()
    create.assert_not_called()


@pytest.mark.parametrize(
    "kind", ["absent", "old_version", "no_flow", "ignored", "configured"]
)
async def test_unavailable_or_existing_companion_is_not_suggested(
    hass, companion, kind
):
    entry, _, installed, _, create = companion
    if kind == "absent":
        installed.clear()
    elif kind == "old_version":
        installed[TRANSLATOR].version = "2026.11.05.2"
    elif kind == "no_flow":
        installed[TRANSLATOR].config_flow = False
    else:
        MockConfigEntry(
            domain=TRANSLATOR, source="ignore" if kind == "ignored" else "user"
        ).add_to_hass(hass)
    async_watch_translator(hass, entry)
    await hass.async_block_till_done()
    create.assert_not_called()


async def test_older_core_keeps_deepl_without_optional_discovery(hass, companion):
    entry, cleanups, _, scan, create = companion
    with patch(f"{MODULE}.MINOR_VERSION", 10):
        async_watch_translator(hass, entry)
    await hass.async_block_till_done()
    assert not cleanups
    scan.assert_not_called()
    create.assert_not_called()
