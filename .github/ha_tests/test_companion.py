"""Optional companion discovery through real Home Assistant lifecycle signals."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
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
    entry = SimpleNamespace(
        async_on_unload=cleanups.append, options={}, entry_id="account"
    )
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
    entry, _, _, scan, create = companion
    with patch(f"{MODULE}.MINOR_VERSION", 10):
        async_watch_translator(hass, entry)
        await hass.async_block_till_done()
    scan.assert_awaited_once()
    create.assert_not_called()


@pytest.mark.parametrize("year,month", [(2023, 7), (2024, 3), (2026, 10)])
async def test_compatible_companion_on_older_core(hass, companion, year, month):
    entry, _, installed, _, create = companion
    installed[TRANSLATOR].version = "2026.11.05.4"
    with (
        patch(f"{MODULE}.MAJOR_VERSION", year),
        patch(f"{MODULE}.MINOR_VERSION", month),
    ):
        async_watch_translator(hass, entry)
        await hass.async_block_till_done()
    create.assert_called_once()


async def test_disabling_discovery_skips_scan_and_events(hass, companion):
    entry, cleanups, _, scan, create = companion
    entry.options["discover_translator"] = False
    async_watch_translator(hass, entry)
    async_dispatcher_send(hass, "hacs_dispatch_repository", {"action": "install"})
    async_dispatcher_send(
        hass, "marketplace_repository_install_progress", {"progress": False}
    )
    await hass.async_block_till_done()
    assert not cleanups
    scan.assert_not_called()
    create.assert_not_called()


@pytest.mark.parametrize("other_enabled", [False, True])
async def test_disable_preserves_other_accounts_and_open_forms(
    hass, companion, other_enabled
):
    entry, _, _, _, _ = companion
    entry.options["discover_translator"] = False
    MockConfigEntry(
        domain="deepl_translator",
        state=ConfigEntryState.LOADED,
        options={"discover_translator": other_enabled},
    ).add_to_hass(hass)
    pending = [
        {
            "handler": TRANSLATOR,
            "context": {"source": "integration_discovery"},
            "step_id": "discovery_confirm",
            "flow_id": "suggestion",
        },
        {
            "handler": TRANSLATOR,
            "context": {"source": "integration_discovery"},
            "step_id": "user",
            "flow_id": "choosing_account",
        },
        {
            "handler": TRANSLATOR,
            "context": {"source": "user"},
            "step_id": "user",
            "flow_id": "manual",
        },
    ]
    with (
        patch.object(hass.config_entries.flow, "async_progress", return_value=pending),
        patch.object(hass.config_entries.flow, "async_abort") as abort,
    ):
        async_watch_translator(hass, entry)
    if other_enabled:
        abort.assert_not_called()
    else:
        abort.assert_called_once_with("suggestion")
