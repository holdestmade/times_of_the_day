"""Support for representing current time of the day as binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time, timedelta
import logging
from typing import Any, Literal, TypeGuard, Union, cast

import voluptuous as vol

from homeassistant.components.binary_sensor import (
    PLATFORM_SCHEMA as BINARY_SENSOR_PLATFORM_SCHEMA,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_AFTER,
    CONF_BEFORE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, event
from homeassistant.helpers.entity_platform import (
    AddConfigEntryEntitiesCallback,
    AddEntitiesCallback,
)
from homeassistant.helpers.sun import get_astral_event_date, get_astral_event_next
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AFTER_OFFSET,
    CONF_AFTER_TIME,
    CONF_BEFORE_OFFSET,
    CONF_BEFORE_TIME,
    CONF_AFTER_MODE,
    CONF_BEFORE_MODE,
    MODE_TIME,
    MODE_SUNRISE,
    MODE_SUNSET,
)

type SunEventType = Literal["sunrise", "sunset"]
TimeOrSun = Union[time, SunEventType]

_LOGGER = logging.getLogger(__name__)

ATTR_AFTER = "after"
ATTR_BEFORE = "before"
ATTR_NEXT_UPDATE = "next_update"

PLATFORM_SCHEMA = BINARY_SENSOR_PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_AFTER): vol.Any(cv.time, vol.All(vol.Lower, cv.sun_event)),
        vol.Required(CONF_BEFORE): vol.Any(cv.time, vol.All(vol.Lower, cv.sun_event)),
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_AFTER_OFFSET, default=timedelta(0)): cv.time_period,
        vol.Optional(CONF_BEFORE_OFFSET, default=timedelta(0)): cv.time_period,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)


def _is_sun_event(sun_event: TimeOrSun) -> TypeGuard[SunEventType]:
    """Return true if event is sun event not time."""
    return sun_event in (SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET)


def _parse_time_or_sun_from_gui(mode: str | None, value: Any) -> TimeOrSun | None:
    """Interpret GUI fields (mode + time) into either a time or a sun event."""
    mode = (mode or MODE_TIME).lower()
    if mode == MODE_SUNRISE:
        return cast(SunEventType, SUN_EVENT_SUNRISE)
    if mode == MODE_SUNSET:
        return cast(SunEventType, SUN_EVENT_SUNSET)
    try:
        return cv.time(value)
    except vol.Invalid:
        return None


def _parse_time_or_sun_text(value: Any) -> TimeOrSun | None:
    """Fallback parser for older entries with plain text 'sunrise'/'sunset' or a time."""
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in (SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET):
            return cast(SunEventType, lower)
        try:
            return cv.time(lower)
        except vol.Invalid:
            return None
    try:
        return cv.time(value)
    except vol.Invalid:
        return None


def _parse_offset(value: Any) -> timedelta:
    """Parse signed minutes (preferred), or duration/time period fallbacks, into timedelta."""
    if value is None:
        return timedelta(0)

    # Preferred: signed integer/float minutes from NumberSelector
    if isinstance(value, (int, float)):
        return timedelta(minutes=float(value))

    # DurationSelector style dict, e.g. {"hours":1, "minutes":-30, "seconds":0}
    try:
        return cv.time_period_dict(value)
    except vol.Invalid:
        pass

    # Text formats like "00:30:00" or "180" seconds, etc.
    try:
        return cv.time_period(value)
    except vol.Invalid:
        return timedelta(0)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Initialize Times of the Day config entry."""
    if hass.config.time_zone is None:
        _LOGGER.error("Timezone is not set in Home Assistant configuration")  # type: ignore[unreachable]
        return

    # Prefer new GUI fields if present
    after = _parse_time_or_sun_from_gui(
        config_entry.options.get(CONF_AFTER_MODE),
        config_entry.options.get(CONF_AFTER_TIME),
    )
    before = _parse_time_or_sun_from_gui(
        config_entry.options.get(CONF_BEFORE_MODE),
        config_entry.options.get(CONF_BEFORE_TIME),
    )

    # Backward compatibility: if modes missing, fall back to text parsing
    if after is None:
        after = _parse_time_or_sun_text(config_entry.options.get(CONF_AFTER_TIME))
    if before is None:
        before = _parse_time_or_sun_text(config_entry.options.get(CONF_BEFORE_TIME))

    if after is None or before is None:
        _LOGGER.error(
            "Invalid Times of the Day configuration. "
            "Please choose a mode (time/sunrise/sunset) and set a valid time when required."
        )
        return

    after_offset = _parse_offset(config_entry.options.get(CONF_AFTER_OFFSET))
    before_offset = _parse_offset(config_entry.options.get(CONF_BEFORE_OFFSET))

    name = config_entry.title
    unique_id = config_entry.entry_id

    async_add_entities(
        [TodSensor(name, after, after_offset, before, before_offset, unique_id)]
    )


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the ToD sensors (YAML)."""
    if hass.config.time_zone is None:
        _LOGGER.error("Timezone is not set in Home Assistant configuration")  # type: ignore[unreachable]
        return

    after = config[CONF_AFTER]
    after_offset = config[CONF_AFTER_OFFSET]
    before = config[CONF_BEFORE]
    before_offset = config[CONF_BEFORE_OFFSET]
    name = config[CONF_NAME]
    unique_id = config.get(CONF_UNIQUE_ID)
    sensor = TodSensor(name, after, after_offset, before, before_offset, unique_id)

    async_add_entities([sensor])


class TodSensor(BinarySensorEntity):
    """Time of the Day Sensor."""

    _attr_should_poll = False
    _time_before: datetime
    _time_after: datetime
    _next_update: datetime

    def __init__(
        self,
        name: str,
        after: TimeOrSun,
        after_offset: timedelta,
        before: TimeOrSun,
        before_offset: timedelta,
        unique_id: str | None,
    ) -> None:
        """Init the ToD Sensor..."""
        self._attr_unique_id = unique_id
        self._attr_name = name
        self._after_offset = after_offset
        self._before_offset = before_offset
        self._before = before
        self._after = after
        self._unsub_update: Callable[[], None] | None = None

    @property
    def is_on(self) -> bool:
        """Return True if sensor is on."""
        now = dt_util.utcnow()
        if self._time_after < self._time_before:
            return self._time_after <= now < self._time_before
        return now >= self._time_after or now < self._time_before

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the state attributes of the sensor."""
        if time_zone := dt_util.get_default_time_zone():
            return {
                ATTR_AFTER: self._time_after.astimezone(time_zone).isoformat(),
                ATTR_BEFORE: self._time_before.astimezone(time_zone).isoformat(),
                ATTR_NEXT_UPDATE: self._next_update.astimezone(time_zone).isoformat(),
            }
        return None

    def _naive_time_to_utc_datetime(self, naive_time: time) -> datetime:
        """Convert naive time from config to utc_datetime with current day."""
        current_local_date = (
            dt_util.utcnow().astimezone(dt_util.get_default_time_zone()).date()
        )
        return dt_util.as_utc(datetime.combine(current_local_date, naive_time))

    def _calculate_boundary_time(self) -> None:
        """Calculate internal absolute time boundaries."""
        nowutc = dt_util.utcnow()

        # AFTER
        if _is_sun_event(self._after):
            after_event_date = get_astral_event_date(
                self.hass, self._after, nowutc
            ) or get_astral_event_next(self.hass, self._after, nowutc)
        else:
            after_event_date = self._naive_time_to_utc_datetime(self._after)

        self._time_after = after_event_date

        # BEFORE
        if _is_sun_event(self._before):
            before_event_date = get_astral_event_date(
                self.hass, self._before, nowutc
            ) or get_astral_event_next(self.hass, self._before, nowutc)

            if before_event_date < after_event_date:
                before_event_date = get_astral_event_next(
                    self.hass, self._before, after_event_date
                )
        else:
            before_event_date = self._naive_time_to_utc_datetime(self._before)

            if before_event_date < after_event_date + self._after_offset:
                before_event_date += timedelta(days=1)

        self._time_before = before_event_date

        # Adjust when both boundaries fell to the "next day" relative to now
        if (
            not _is_sun_event(self._after)
            and self._time_after > nowutc
            and self._time_before > nowutc + timedelta(days=1)
        ):
            self._time_after -= timedelta(days=1)
            self._time_before -= timedelta(days=1)

        # Apply offsets
        self._time_after += self._after_offset
        self._time_before += self._before_offset

    def _add_one_dst_aware_day(self, a_date: datetime, target_time: time) -> datetime:
        """Add 24 hours (1 day) but account for DST."""
        tentative_new_date = a_date + timedelta(days=1)
        tentative_new_date = dt_util.as_local(tentative_new_date)
        tentative_new_date = tentative_new_date.replace(
            hour=target_time.hour, minute=target_time.minute
        )
        return dt_util.find_next_time_expression_time(
            tentative_new_date,
            dt_util.parse_time_expression("*", 0, 59),
            dt_util.parse_time_expression("*", 0, 59),
            dt_util.parse_time_expression("*", 0, 23),
        )

    def _turn_to_next_day(self) -> None:
        """Turn to to the next day."""
        if _is_sun_event(self._after):
            self._time_after = get_astral_event_next(
                self.hass, self._after, self._time_after - self._after_offset
            )
            self._time_after += self._after_offset
        else:
            self._time_after = self._add_one_dst_aware_day(
                self._time_after, self._after
            )

        if _is_sun_event(self._before):
            self._time_before = get_astral_event_next(
                self.hass, self._before, self._time_before - self._before_offset
            )
            self._time_before += self._before_offset
        else:
            self._time_before = self._add_one_dst_aware_day(
                self._time_before, self._before
            )

    async def async_added_to_hass(self) -> None:
        """Call when entity about to be added to Home Assistant."""
        self._calculate_boundary_time()
        self._calculate_next_update()

        @callback
        def _clean_up_listener() -> None:
            if self._unsub_update is not None:
                self._unsub_update()
                self._unsub_update = None

        self.async_on_remove(_clean_up_listener)

        self._unsub_update = event.async_track_point_in_utc_time(
            self.hass, self._point_in_time_listener, self._next_update
        )

    def _calculate_next_update(self) -> None:
        """Datetime when the next update to the state."""
        now = dt_util.utcnow()
        if now < self._time_after:
            self._next_update = self._time_after
            return
        if now < self._time_before:
            self._next_update = self._time_before
            return
        self._turn_to_next_day()
        self._next_update = self._time_after

    @callback
    def _point_in_time_listener(self, now: datetime) -> None:
        """Run when the state of the sensor should be updated."""
        self._calculate_next_update()
        self.async_write_ha_state()

        self._unsub_update = event.async_track_point_in_utc_time(
            self.hass, self._point_in_time_listener, self._next_update
        )
