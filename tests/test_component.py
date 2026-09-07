"""Real HA/PyHAP objects; no network listeners or live TV used."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
import yaml
from homeassistant.components.homekit import CONFIG_SCHEMA as HOMEKIT_SCHEMA
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.components.homekit.accessories import TYPES
from homeassistant.components.homekit.iidmanager import AccessoryIIDStorage
from homeassistant.components.homekit.type_media_players import TelevisionMediaPlayer
from pyhap.loader import get_loader

from custom_components.lg_tv_homekit import CONFIG_SCHEMA, async_setup
import custom_components.lg_tv_homekit as integration

CONFIG = {
    "lg_tv_homekit": {
        "tv_entity_id": "media_player.tv",
        "backlight_entity_id": "number.tv_backlight",
    }
}


def test_example_yaml():
    config = yaml.safe_load(
        (Path(__file__).parents[1] / "configuration.example.yaml").read_text()
    )
    CONFIG_SCHEMA(config)
    HOMEKIT_SCHEMA(config)


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch, request):
    hass = HomeAssistant(str(tmp_path))
    hass.states.async_set(
        "media_player.tv",
        "on",
        {
            "device_class": "tv",
            "supported_features": int(MediaPlayerEntityFeature.SELECT_SOURCE),
            "source_list": ["Apple", "PS5", "YouTube"],
            "source": "Apple",
        },
    )
    hass.states.async_set(
        "number.tv_backlight", "40", {"min": 0, "max": 100, "step": 1}
    )
    original = TYPES["TelevisionMediaPlayer"]
    monkeypatch.setitem(TYPES, "TelevisionMediaPlayer", original)
    config = {
        "lg_tv_homekit": {**CONFIG["lg_tv_homekit"], **getattr(request, "param", {})}
    }
    assert await async_setup(hass, CONFIG_SCHEMA(config))
    storage = AccessoryIIDStorage(hass, "test-entry")
    storage.store = MagicMock()
    driver = MagicMock()
    driver.loader = get_loader()
    driver.iid_storage = storage
    driver.entry_id = "test-entry"
    accessory = TYPES["TelevisionMediaPlayer"](
        hass, driver, "LG TV", "media_player.tv", 1, {}
    )
    accessory.run()
    calls = []

    @callback
    def record(call):
        calls.append((call.domain, call.service, dict(call.data)))
        if call.domain == "number":
            hass.states.async_set(
                "number.tv_backlight",
                str(call.data["value"]),
                {"min": 0, "max": 100, "step": 1},
            )

    hass.services.async_register("number", "set_value", record)
    hass.services.async_register("media_player", "turn_on", record)
    hass.services.async_register("media_player", "turn_off", record)
    hass.services.async_register("media_player", "select_source", record)
    yield hass, accessory, calls, driver
    accessory.async_stop()
    TYPES["TelevisionMediaPlayer"] = original
    await hass.async_block_till_done()


async def drain(hass):
    await asyncio.sleep(0)
    await hass.async_block_till_done()


@pytest.mark.asyncio
async def test_single_accessory_link_and_stable_iids(env):
    hass, acc, _, driver = env
    hap = acc.to_HAP()
    tv = next(s for s in hap["services"] if s["type"] == "D8")
    light = next(s for s in hap["services"] if s["type"] == "43")
    assert light["iid"] in tv["linked"]
    assert hap["aid"] == 1
    second = TYPES["TelevisionMediaPlayer"](
        hass, driver, "LG TV", "media_player.tv", 1, {}
    )
    assert second.to_HAP() == hap
    second.async_stop()


@pytest.mark.asyncio
async def test_brightness_off_on_and_tv_power(env):
    hass, acc, calls, _ = env
    b = acc._lg_backlight
    b.brightness.client_update_value(30)
    await drain(hass)
    assert calls == [
        ("number", "set_value", {"entity_id": "number.tv_backlight", "value": 30})
    ]
    b.on.client_update_value(False)
    await drain(hass)
    assert calls[-1][2]["value"] == 0
    assert b.on.value is True and b.brightness.value == 0
    before = len(calls)
    b.on.client_update_value(True)
    await drain(hass)
    assert len(calls) == before
    acc.set_on_off(False)
    await drain(hass)
    assert calls[-1][:2] == ("media_player", "turn_off")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["off", "standby", "unknown", "unavailable", None])
async def test_no_wake_and_no_deferred_commands(env, state):
    hass, acc, calls, _ = env
    if state is None:
        hass.states.async_remove("media_player.tv")
    else:
        hass.states.async_set("media_player.tv", state)
    await drain(hass)
    b = acc._lg_backlight
    b.set_brightness(85)
    b.set_on(False)
    b.set_on(True)
    await drain(hass)
    assert not calls
    assert b.snapshot() == (False, 0)
    hass.states.async_set("media_player.tv", "on")
    await drain(hass)
    assert not calls and b.snapshot() == (True, 40)


@pytest.mark.asyncio
async def test_ha_updates_and_missing_number(env):
    hass, acc, calls, _ = env
    b = acc._lg_backlight
    hass.states.async_set("number.tv_backlight", "67", {"min": 0, "max": 100})
    await drain(hass)
    assert b.brightness.value == 67
    hass.states.async_remove("number.tv_backlight")
    await drain(hass)
    assert b.fault.value == 1
    b.set_brightness(23)
    await drain(hass)
    assert not calls


@pytest.mark.asyncio
async def test_failed_write_resync(env):
    hass, acc, _, _ = env

    async def fail(call):
        raise RuntimeError("Simulated TV failure")

    hass.services.async_register("number", "set_value", fail)
    acc._lg_backlight.brightness.client_update_value(90)
    await drain(hass)
    assert acc._lg_backlight.brightness.value == 40


@pytest.mark.asyncio
async def test_queued_write_dropped_after_power_cycle(env):
    hass, acc, calls, _ = env
    b = acc._lg_backlight
    await b._lock.acquire()
    b.set_brightness(90)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    hass.states.async_set("media_player.tv", "off")
    await asyncio.sleep(0)
    hass.states.async_set("media_player.tv", "on")
    b._lock.release()
    await drain(hass)
    assert not calls


@pytest.mark.asyncio
async def test_stop_and_other_tv(env):
    hass, acc, calls, driver = env
    hass.states.async_set("media_player.other", "on", {"supported_features": 0})
    other = TYPES["TelevisionMediaPlayer"](
        hass, driver, "Other", "media_player.other", 2, {}
    )
    assert other._lg_backlight is None
    assert all(s["type"] != "43" for s in other.to_HAP()["services"])
    acc.async_stop()
    acc._lg_backlight.set_brightness(22)
    await drain(hass)
    assert not calls and acc._lg_backlight._unsub is None
    other.async_stop()


@pytest.mark.asyncio
async def test_version_guard(tmp_path, monkeypatch):
    hass = HomeAssistant(str(tmp_path))
    original = TYPES["TelevisionMediaPlayer"]
    monkeypatch.setattr(integration, "HA_VERSION", "2099.1.0")
    assert not await async_setup(hass, CONFIG)
    assert TYPES["TelevisionMediaPlayer"] is original


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["unavailable", "unknown", "nan", "inf", "101", "-1"])
async def test_invalid_number_values(env, value):
    hass, acc, calls, _ = env
    hass.states.async_set("number.tv_backlight", value, {"min": 0, "max": 100})
    await drain(hass)
    acc._lg_backlight.set_brightness(50)
    await drain(hass)
    assert not calls and acc._lg_backlight.fault.value == 1


@pytest.mark.asyncio
async def test_on_off_on_immediate_events_drop_queued_write(env):
    hass, acc, calls, _ = env
    b = acc._lg_backlight
    await b._lock.acquire()
    b.set_brightness(90)
    await asyncio.sleep(0)
    hass.states.async_set("media_player.tv", "off")
    hass.states.async_set("media_player.tv", "on")
    await asyncio.sleep(0)
    b._lock.release()
    await drain(hass)
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [{"show_inputs": False}], indirect=True)
async def test_hide_inputs_keeps_tv_and_backlight(env):
    hass, acc, calls, driver = env
    types = [s["type"] for s in acc.to_HAP()["services"]]
    assert "D9" not in types  # InputSource
    assert "D8" in types and "43" in types  # Television and Lightbulb
    assert not acc.support_select_source
    acc.set_input_source(0)
    await drain(hass)
    assert not calls
    hass.states.async_set(
        "media_player.other",
        "on",
        {
            "supported_features": int(MediaPlayerEntityFeature.SELECT_SOURCE),
            "source_list": ["HDMI 1"],
        },
    )
    other = TYPES["TelevisionMediaPlayer"](
        hass, driver, "Other", "media_player.other", 2, {}
    )
    assert other.sources == ["HDMI 1"]
    other.async_stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [{"include_sources": ["PS5"]}], indirect=True)
async def test_filter_inputs_and_avoid_fake_selection(env):
    hass, acc, calls, _ = env
    assert acc.sources == ["PS5"]
    assert acc.char_input_source.value == 999999  # Apple is not exported.
    acc.set_input_source(0)
    await drain(hass)
    assert calls[-1][2]["source"] == "PS5"
    attrs = dict(hass.states.get("media_player.tv").attributes)
    attrs["source"] = "PS5"
    hass.states.async_set("media_player.tv", "on", attrs)
    await drain(hass)
    assert acc.char_input_source.value == 0
    hass.states.async_set("media_player.tv", "off", attrs)
    await drain(hass)
    assert acc.char_input_source.value == 999999


def test_compatibility_rejects_changed_contract():
    from custom_components.lg_tv_homekit.compatibility import compatible

    class Changed(TelevisionMediaPlayer):
        def set_input_source(self, value, extra):
            pass

    assert not compatible("2026.9.1", "5.0.0", Changed)
    assert not compatible("2026.9.1", "6.0.0", TelevisionMediaPlayer)


@pytest.mark.asyncio
async def test_iids_survive_real_local_storage_reload(env):
    hass, acc, _, driver = env
    storage = AccessoryIIDStorage(hass, "local-iid-regression")
    await storage.async_initialize()
    driver.iid_storage = storage
    first = TYPES["TelevisionMediaPlayer"](
        hass, driver, "LG TV", "media_player.tv", 1, {}
    )
    first_hap = first.to_HAP()
    await storage.async_save()
    reloaded = AccessoryIIDStorage(hass, "local-iid-regression")
    await reloaded.async_initialize()
    assert reloaded.allocations == storage.allocations
    driver.iid_storage = reloaded
    second = TYPES["TelevisionMediaPlayer"](
        hass, driver, "LG TV", "media_player.tv", 1, {}
    )
    assert second.to_HAP() == first_hap
    await reloaded.async_save()
