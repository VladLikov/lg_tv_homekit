"""Opt-in HomeKit TV extension for reviewed Home Assistant releases."""

from __future__ import annotations

import logging
from importlib.metadata import version

import voluptuous as vol
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

DOMAIN = "lg_tv_homekit"
_LOGGER = logging.getLogger(__name__)


def _entity(domain):
    def validate(value):
        value = cv.entity_id(value)
        if value.split(".")[0] != domain:
            raise vol.Invalid(f"Expected a {domain} entity")
        return value

    return validate


CONFIG_SCHEMA = vol.Schema(
    {
        vol.Optional(DOMAIN): vol.Schema(
            {
                vol.Required("tv_entity_id"): _entity("media_player"),
                vol.Required("backlight_entity_id"): _entity("number"),
                vol.Optional("show_inputs", default=True): cv.boolean,
                vol.Optional("include_sources"): [cv.string],
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass, config):
    """Install a scoped registry extension before HomeKit starts its driver."""
    if DOMAIN not in config:
        return True
    if hass.is_running:
        _LOGGER.error("Configure lg_tv_homekit in YAML, then restart Home Assistant")
        return False

    from homeassistant.components.homekit.accessories import TYPES
    from homeassistant.components.homekit.type_media_players import (
        TelevisionMediaPlayer,
    )
    from pyhap.util import callback as pyhap_callback

    from .backlight import Backlight
    from .compatibility import compatible

    hap_version = await hass.async_add_executor_job(version, "HAP-python")
    if not compatible(HA_VERSION, hap_version, TelevisionMediaPlayer):
        _LOGGER.error(
            "Unsupported HomeKit contract: Core %s / HAP-python %s; see compatibility matrix",
            HA_VERSION,
            hap_version,
        )
        return False

    original = TYPES["TelevisionMediaPlayer"]
    if original is not TelevisionMediaPlayer:
        _LOGGER.error(
            "Another extension already replaced TelevisionMediaPlayer; refusing conflict"
        )
        return False
    settings = config[DOMAIN]

    class LGTelevisionMediaPlayer(TelevisionMediaPlayer):
        """Keep standard TV behavior; attach Backlight only to the selected entity."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._lg_backlight = None
            if self.hass is hass and self.entity_id == settings["tv_entity_id"]:
                self._lg_backlight = Backlight(self, settings["backlight_entity_id"])

        def _is_selected_tv(self):
            return self.hass is hass and self.entity_id == settings["tv_entity_id"]

        def _get_ordered_source_list_from_state(self, state):
            sources = super()._get_ordered_source_list_from_state(state)
            if not self._is_selected_tv():
                return sources
            if not settings.get("show_inputs", True):
                return []
            if "include_sources" not in settings:
                return sources
            # Compare the original HA labels, before HomeKit name sanitization.
            allowed = settings["include_sources"]
            return [
                source for source in sources if self._mapped_sources[source] in allowed
            ]

        @callback
        def _async_update_input_state(self, hk_state, new_state):
            if not self._is_selected_tv():
                return super()._async_update_input_state(hk_state, new_state)
            if not self.support_select_source:
                return
            source = new_state.attributes.get(self.source_key)
            for index, name in enumerate(self.sources):
                if hk_state and self._mapped_sources.get(name) == source:
                    self.char_input_source.set_value(index)
                    return
            # Homebridge likewise uses a non-existing ID when no input is active.
            self.char_input_source.set_value(999999)

        def set_input_source(self, value):
            if self._is_selected_tv() and (
                not self.support_select_source or not 0 <= value < len(self.sources)
            ):
                return
            super().set_input_source(value)

        @callback
        @pyhap_callback
        def run(self):
            super().run()
            if self._lg_backlight:
                self._lg_backlight.start()

        @callback
        def async_stop(self):
            if self._lg_backlight:
                self._lg_backlight.stop()
            super().async_stop()

    # Only process memory is changed. Core files and PyHAP are never modified.
    # The original entry is recreated naturally on restart after removal.
    TYPES["TelevisionMediaPlayer"] = LGTelevisionMediaPlayer
    hass.data[DOMAIN] = settings
    _LOGGER.info("Backlight extension enabled for %s", settings["tv_entity_id"])
    return True
