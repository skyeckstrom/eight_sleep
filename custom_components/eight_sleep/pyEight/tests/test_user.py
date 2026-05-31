import asyncio
import unittest
from unittest.mock import AsyncMock, patch, call # Add 'call' for checking multiple calls
from datetime import datetime, time as dt_time, timedelta, timezone # Import datetime for away_mode test

# Assuming similar import structure as test_auth.py
from custom_components.eight_sleep.pyEight.eight import EightSleep
from custom_components.eight_sleep.pyEight.user import EightUser
from custom_components.eight_sleep.pyEight.constants import APP_API_URL # For URL construction

class TestEightUser(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        # Mock EightSleep device instance.
        # Tests for EightUser will typically mock calls to self.device.api_request
        self.mock_eight_device = AsyncMock(spec=EightSleep)
        self.mock_eight_device.timezone = "America/New_York" # Needed for convert_string_to_datetime

        # Mock device_data on the EightSleep instance if properties rely on it directly
        self.mock_eight_device.device_data = {}
        self.mock_eight_device.device_id = "fake_device_id_for_user_tests"


        self.user_id = "test_user_123"
        self.user_side = "left"
        self.user = EightUser(self.mock_eight_device, self.user_id, self.user_side)

    async def test_set_heating_level(self):
        # Reset mock for each test
        self.mock_eight_device.api_request = AsyncMock()
        # Mock the get_current_heating_level call made before turning on side if needed
        # For set_heating_level, it calls turn_on_side() first.
        # turn_on_side() also calls api_request.

        # To simplify, we can assume turn_on_side works or mock its specific api_request call.
        # Let's mock the sequence of calls expected from set_heating_level:
        # 1. PUT to .../temperature for turn_on_side {"currentState": {"type": "smart"}}
        # 2. PUT to .../temperature for set_heating_level {"currentLevel": 50}
        # 3. PUT to .../temperature for set_heating_level {"timeBased": {"level": 50, "durationSeconds": 7200}}

        self.mock_eight_device.api_request.return_value = {} # Successful API call returns something

        await self.user.set_heating_level(level=50, duration=7200)

        expected_url = f"{APP_API_URL}v1/users/{self.user_id}/temperature"

        # Check the calls made to api_request
        self.assertEqual(self.mock_eight_device.api_request.call_count, 3)

        calls = self.mock_eight_device.api_request.call_args_list

        # Call 1: turn_on_side
        self.assertEqual(calls[0], call('PUT', expected_url, data={'currentState': {'type': 'smart'}}))

        # Call 2: set_heating_level (currentLevel)
        self.assertEqual(calls[1], call('PUT', expected_url, data={'currentLevel': 50}))

        # Call 3: set_heating_level (timeBased)
        self.assertEqual(calls[2], call('PUT', expected_url, data={'timeBased': {'level': 50, 'durationSeconds': 7200}}))

    @patch('custom_components.eight_sleep.pyEight.user.datetime') # Mock datetime within user.py
    async def test_set_away_mode_start(self, mock_datetime):
        self.mock_eight_device.api_request = AsyncMock(return_value={})

        # Mock datetime.utcnow() to return a fixed time for predictable payload
        fixed_utcnow = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.utcnow.return_value = fixed_utcnow

        # The method calculates 'now' as 24 hours ago
        expected_api_timestamp = (fixed_utcnow - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        await self.user.set_away_mode("start")

        expected_url = f"{APP_API_URL}v1/users/{self.user_id}/away-mode"
        expected_payload = {"awayPeriod": {"start": expected_api_timestamp}}

        self.mock_eight_device.api_request.assert_called_once_with(
            'PUT', expected_url, data=expected_payload
        )

    async def test_current_hrv_property_with_data(self):
        # Mock the user's trends data
        self.user.trends = [
            { # Trend 0 (current)
                "sessions": [{
                    "timeseries": { "heartRate": [["ts", 60]] }, # Minimal timeseries
                }],
                "sleepQualityScore": {
                    "hrv": {"current": 55.0}
                }
            }
        ]
        self.assertEqual(self.user.current_hrv, 55.0)

    async def test_current_hrv_property_no_data(self):
        self.user.trends = [] # No trend data
        self.assertIsNone(self.user.current_hrv)

    async def test_current_hrv_property_missing_keys(self):
        self.user.trends = [
            {
                "sessions": [{}],
                "sleepQualityScore": {} # Missing hrv or current
            }
        ]
        self.assertIsNone(self.user.current_hrv)

    async def test_current_hrv_property_string_none(self):
        # Test the fix for string "None"
        self.user.trends = [
            {
                "sessions": [{}],
                "sleepQualityScore": {
                    "hrv": {"current": "None"}
                }
            }
        ]
        self.assertIsNone(self.user.current_hrv)

    async def test_corrected_side_for_key(self):
        self.assertEqual(self.user.corrected_side_for_key, "left")

        self.user.side = "right"
        self.assertEqual(self.user.corrected_side_for_key, "right")

        self.user.side = "solo"
        self.assertEqual(self.user.corrected_side_for_key, "left")

        with patch('custom_components.eight_sleep.pyEight.user._LOGGER') as mock_logger:
            self.user.side = None
            self.assertEqual(self.user.corrected_side_for_key, "left")
            mock_logger.warning.assert_called_once()

    async def test_set_bedtime_schedule(self):
        # Response nests the updated list under "settings" (the update DTO shape).
        self.mock_eight_device.api_request = AsyncMock(return_value={
            "settings": {"schedules": [{"id": "abc", "enabled": True}]}
        })

        schedules = [
            {
                "id": "abc",
                "enabled": True,
                "time": dt_time(22, 30),            # datetime.time -> "22:30:00"
                "days": ["MONDAY", "Tuesday"],      # mixed case -> lowercased
                "tags": [],                          # unknown field, must be preserved
                "startSettings": {"bedtime": -34},
            }
        ]

        resp = await self.user.set_bedtime_schedule(schedules)

        expected_url = f"{APP_API_URL}v1/users/{self.user_id}/bedtime"
        self.mock_eight_device.api_request.assert_called_once_with(
            "PUT",
            expected_url,
            data={
                "schedules": [
                    {
                        "id": "abc",
                        "enabled": True,
                        "time": "22:30:00",
                        "days": ["monday", "tuesday"],
                        "tags": [],
                        "startSettings": {"bedtime": -34},
                    }
                ]
            },
        )
        # bedtime_schedules refreshed from the parsed response
        self.assertEqual(self.user.bedtime_schedules, [{"id": "abc", "enabled": True}])
        self.assertEqual(resp, {"settings": {"schedules": [{"id": "abc", "enabled": True}]}})

    async def test_set_bedtime_schedule_normalizes_short_time(self):
        self.mock_eight_device.api_request = AsyncMock(return_value={})
        await self.user.set_bedtime_schedule([{"time": "23:00", "days": ["sunday"]}])
        sent = self.mock_eight_device.api_request.call_args.kwargs["data"]["schedules"][0]
        self.assertEqual(sent["time"], "23:00:00")

    async def test_set_bedtime_schedule_response_top_level_schedules(self):
        # Defensive fallback: some responses carry schedules at the top level.
        self.mock_eight_device.api_request = AsyncMock(return_value={
            "schedules": [{"id": "xyz"}]
        })
        await self.user.set_bedtime_schedule([{"id": "xyz", "time": "22:00:00"}])
        self.assertEqual(self.user.bedtime_schedules, [{"id": "xyz"}])

    async def test_update_bedtime_schedules(self):
        self.mock_eight_device.api_request = AsyncMock(return_value={
            "schedules": [{"id": "s1", "time": "22:00:00", "days": ["monday"]}],
            "currentSchedule": {},
        })
        await self.user.update_bedtime_schedules()
        expected_url = f"{APP_API_URL}v1/users/{self.user_id}/temperature/all"
        self.mock_eight_device.api_request.assert_called_once_with("GET", expected_url)
        self.assertEqual(
            self.user.bedtime_schedules,
            [{"id": "s1", "time": "22:00:00", "days": ["monday"]}],
        )


if __name__ == '__main__':
    unittest.main()
