"""Unit tests for the set_bedtime_schedule entity-service handler.

These cover the handler's read-modify-write logic: target selection, mutation,
and preserving the other schedules plus the target's unknown fields. The pyEight
set_bedtime_schedule call is mocked, so its serialization is not retested here
(see pyEight/tests/test_user.py for that).
"""

import unittest
from datetime import time as dt_time
from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError

from custom_components.eight_sleep import DOMAIN, EightSleepBaseEntity


def _make_entity(schedules):
    """Build an entity with __init__ bypassed and just the fields the handler uses."""
    entity = EightSleepBaseEntity.__new__(EightSleepBaseEntity)
    user = MagicMock()
    user.bedtime_schedules = schedules
    user.update_bedtime_schedules = AsyncMock()
    user.set_bedtime_schedule = AsyncMock()
    entity._user_obj = user

    entry = MagicMock()
    entry.entry_id = "entry1"
    entity._config_entry = entry

    config_entry_data = MagicMock()
    config_entry_data.user_coordinator.async_request_refresh = AsyncMock()
    entity.hass = MagicMock()
    entity.hass.data = {DOMAIN: {"entry1": config_entry_data}}
    return entity, user


class TestSetBedtimeScheduleService(unittest.IsolatedAsyncioTestCase):

    async def test_update_sole_schedule_preserves_unknown_fields(self):
        entity, user = _make_entity([
            {
                "id": "s1",
                "enabled": True,
                "time": "22:00:00",
                "days": ["monday"],
                "tags": [],
                "startSettings": {"bedtime": -30},
            }
        ])
        await entity.async_set_bedtime_schedule(time=dt_time(23, 15))

        user.set_bedtime_schedule.assert_awaited_once()
        sent = user.set_bedtime_schedule.await_args.args[0]
        self.assertEqual(len(sent), 1)
        # time mutated; id/days/tags/startSettings preserved untouched
        self.assertEqual(sent[0]["time"], dt_time(23, 15))
        self.assertEqual(sent[0]["id"], "s1")
        self.assertEqual(sent[0]["tags"], [])
        self.assertEqual(sent[0]["startSettings"], {"bedtime": -30})

    async def test_target_by_id_leaves_other_schedules_untouched(self):
        original = [
            {"id": "a", "enabled": True, "time": "21:00:00", "days": ["monday"]},
            {"id": "b", "enabled": True, "time": "23:00:00", "days": ["friday"]},
        ]
        entity, user = _make_entity([dict(s) for s in original])
        await entity.async_set_bedtime_schedule(
            schedule_id="b", enabled=False, bedtime_temperature=10
        )

        sent = user.set_bedtime_schedule.await_args.args[0]
        # schedule "a" unchanged
        self.assertEqual(sent[0], original[0])
        # schedule "b" mutated: enabled flipped, startSettings.bedtime set
        self.assertEqual(sent[1]["enabled"], False)
        self.assertEqual(sent[1]["startSettings"], {"bedtime": 10})
        self.assertEqual(sent[1]["time"], "23:00:00")

    async def test_ambiguous_without_id_raises(self):
        entity, user = _make_entity([
            {"id": "a", "time": "21:00:00"},
            {"id": "b", "time": "23:00:00"},
        ])
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_bedtime_schedule(time=dt_time(22, 0))
        user.set_bedtime_schedule.assert_not_awaited()

    async def test_unknown_id_raises(self):
        entity, user = _make_entity([{"id": "a", "time": "21:00:00"}])
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_bedtime_schedule(schedule_id="missing")
        user.set_bedtime_schedule.assert_not_awaited()

    async def test_create_new_when_none_exist(self):
        entity, user = _make_entity([])
        await entity.async_set_bedtime_schedule(
            time=dt_time(22, 30), days=["monday", "tuesday"], bedtime_temperature=-20
        )
        sent = user.set_bedtime_schedule.await_args.args[0]
        self.assertEqual(len(sent), 1)
        self.assertIsNone(sent[0]["id"])
        self.assertEqual(sent[0]["enabled"], True)
        self.assertEqual(sent[0]["time"], dt_time(22, 30))
        self.assertEqual(sent[0]["days"], ["monday", "tuesday"])
        self.assertEqual(sent[0]["startSettings"], {"bedtime": -20})

    async def test_create_new_requires_time_and_days(self):
        entity, user = _make_entity([])
        with self.assertRaises(HomeAssistantError):
            await entity.async_set_bedtime_schedule(enabled=True)
        user.set_bedtime_schedule.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
