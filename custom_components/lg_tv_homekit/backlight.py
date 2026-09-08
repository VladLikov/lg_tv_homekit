"""Linked Lightbulb service with Homebridge-compatible picture-setting behavior."""

from __future__ import annotations

import asyncio
import logging
import math

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)
_OFF = {"off", "standby", "unknown", "unavailable", "None"}


class Backlight:
    """All state and service operations execute on the HA event loop."""

    def __init__(self, accessory, entity_id):
        self.hass = accessory.hass
        self.tv_id = accessory.entity_id
        self.entity_id = entity_id
        self._stopped = False
        self._unsub = None
        self._tasks = set()
        self._lock = asyncio.Lock()
        self._epoch = 0
        service = accessory.add_preload_service(
            "Lightbulb",
            ["Name", "Brightness", "ConfiguredName", "StatusFault"],
            unique_id="lg_tv_homekit_backlight",
        )
        self.service = service
        service.configure_char("Name", value="Backlight")
        service.configure_char("ConfiguredName", value="Backlight")
        self.on = service.configure_char(
            "On",
            value=False,
            setter_callback=self.set_on,
            getter_callback=lambda: self.snapshot()[0],
        )
        self.brightness = service.configure_char(
            "Brightness",
            value=0,
            setter_callback=self.set_brightness,
            getter_callback=lambda: self.snapshot()[1],
        )
        self.fault = service.configure_char("StatusFault", value=0)
        accessory.serv_tv.add_linked_service(service)

    def powered(self):
        state = self.hass.states.get(self.tv_id)
        return state is not None and state.state not in _OFF

    def level(self):
        state = self.hass.states.get(self.entity_id)
        if state is None:
            return None
        try:
            value = float(state.state)
            lower = float(state.attributes["min"])
            upper = float(state.attributes["max"])
            if not all(math.isfinite(x) for x in (value, lower, upper)):
                return None
            if lower > 0 or upper < 100 or not 0 <= value <= 100:
                return None
            return round(value)
        except (ValueError, TypeError, KeyError):
            return None

    def snapshot(self):
        if not self.powered():
            return False, 0
        level = self.level()
        # Apple Home must not receive an enabled light with zero brightness.
        # Backlight power is independent of the Television power characteristic.
        return level is not None and level > 0, level or 0

    @callback
    def sync(self):
        if self._stopped:
            return
        on, brightness = self.snapshot()
        self.on.set_value(on)
        self.brightness.set_value(brightness)
        self.fault.set_value(int(self.powered() and self.level() is None))

    @callback
    def _changed(self, event):
        if event.data["entity_id"] == self.tv_id:
            state = event.data["new_state"]
            if state is None or state.state in _OFF:
                self._epoch += 1
        self.sync()

    @callback
    def start(self):
        if self._unsub is not None:
            return
        self._unsub = async_track_state_change_event(
            self.hass,
            [self.tv_id, self.entity_id],
            self._changed,
        )
        self.sync()

    @callback
    def stop(self):
        self._stopped = True
        if self._unsub:
            self._unsub()
            self._unsub = None
        for task in tuple(self._tasks):
            task.cancel()

    def set_on(self, value):
        # Homebridge treats On=true as a no-op; it does not restore a saved level.
        self.hass.loop.call_soon_threadsafe(
            self._queue,
            0 if not value and self.powered() else None,
            self._epoch,
        )

    def set_brightness(self, value):
        self.hass.loop.call_soon_threadsafe(
            self._queue,
            value if self.powered() else None,
            self._epoch,
        )

    @callback
    def _queue(self, value, epoch):
        if self._stopped:
            return
        if (
            value is None
            or epoch != self._epoch
            or not self.powered()
            or self.level() is None
        ):
            self.sync()
            return
        try:
            numeric = float(value)
            if not math.isfinite(numeric) or not 0 <= numeric <= 100:
                raise ValueError
            value = round(numeric)
        except (TypeError, ValueError):
            self.sync()
            return
        task = self.hass.async_create_task(self._write(value, self._epoch))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _write(self, value, epoch):
        try:
            async with self._lock:
                # Recheck after waiting: a queued slider command must not survive TV-off.
                if (
                    self._stopped
                    or epoch != self._epoch
                    or not self.powered()
                    or self.level() is None
                ):
                    return
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": self.entity_id, "value": value},
                    blocking=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Backlight write failed for %s", self.entity_id)
        finally:
            # HA is authoritative, including rejected writes and optimistic HAP changes.
            self.sync()
