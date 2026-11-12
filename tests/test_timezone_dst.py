"""DST fixtures use execution dates rather than the host's current UTC offset."""
import asyncio
import datetime as dt
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from dateutil import tz
from framework_common.schedule_service.timezone_helper import TimezoneHelper as TZ, ZoneInfoNotFoundError
from test_core_reply_mentions_profile import definitions


class TimezoneTests(unittest.TestCase):
    def test_stuttgart_aliases_and_iana_names(self):
        for name in ('斯图加特', 'Stuttgart', '德国斯图加特', 'Germany Stuttgart'):
            self.assertEqual(TZ.resolve_timezone(name)[1], 'Europe/Berlin')
        self.assertEqual(TZ.resolve_timezone('Europe/Bratislava')[1], 'Europe/Bratislava')

    def test_zero_and_signed_minute_offsets(self):
        for name, expected in (('UTC', 0), ('GMT', 0), ('Z', 0), ('UTC-3:30', -3.5),
                               ('UTC-00:30', -0.5), ('UTC+05:30', 5.5)):
            zone, _, hours = TZ.resolve_timezone(name)
            self.assertEqual(hours, expected)
            self.assertEqual(dt.datetime(2026, 1, 1, tzinfo=zone).utcoffset().total_seconds() / 3600, expected)
        for name in ('UTC+24', 'UTC-03:60'):
            with self.assertRaises(ValueError):
                TZ.resolve_timezone(name)

    def test_winter_and_summer_use_target_date(self):
        for month, utc_hour in ((1, 8), (7, 7)):
            now = dt.datetime(2026, month, 15, tzinfo=dt.timezone.utc)
            result = TZ.compute_next_bot_run_time(9, 0, 'Stuttgart', from_bot_dt=now)
            self.assertEqual(result.astimezone(dt.timezone.utc).hour, utc_hour)

    def test_spring_gap_moves_forward_by_gap(self):
        result = TZ.compute_next_bot_run_time(2, 30, 'Stuttgart',
                    from_bot_dt=dt.datetime(2026, 3, 29, tzinfo=dt.timezone.utc))
        local = result.astimezone(tz.gettz('Europe/Berlin'))
        self.assertEqual((local.day, local.hour, local.minute), (29, 3, 30))

    def test_autumn_fold_runs_first_occurrence_only(self):
        first = TZ.compute_next_bot_run_time(2, 30, 'Stuttgart',
                    from_bot_dt=dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc))
        self.assertEqual(first.astimezone(dt.timezone.utc), dt.datetime(2026, 10, 25, 0, 30, tzinfo=dt.timezone.utc))
        after_first = TZ.compute_next_bot_run_time(2, 30, 'Stuttgart',
                    from_bot_dt=dt.datetime(2026, 10, 25, 1, 0, tzinfo=dt.timezone.utc))
        self.assertEqual(after_first.astimezone(dt.timezone.utc), dt.datetime(2026, 10, 26, 1, 30, tzinfo=dt.timezone.utc))

    def test_dateutil_fallback_requires_no_new_timezone_package(self):
        with patch('framework_common.schedule_service.timezone_helper.ZoneInfo', side_effect=ZoneInfoNotFoundError):
            zone, _, _ = TZ.resolve_timezone('Stuttgart')
            for month, hours in ((1, 1), (7, 2)):
                self.assertEqual(dt.datetime(2026, month, 1, tzinfo=zone).utcoffset(), dt.timedelta(hours=hours))


class AsyncTimezoneTests(unittest.IsolatedAsyncioTestCase):
    async def test_listing_resolves_city_in_worker_and_displays_task_zone(self):
        main_id = threading.get_ident()
        threads = []

        def resolve(value):
            threads.append(threading.get_ident())
            return tz.gettz('Europe/Berlin'), 'Europe/Berlin', 1

        task = NS(target_city='Stuttgart', target_timezone='Europe/Berlin',
                  next_run_timestamp=dt.datetime(2026, 1, 1, 8, tzinfo=dt.timezone.utc).timestamp(),
                  action_type='message', time_str='09:00', recur_type='daily', description='fixture')
        scheduler = NS(list_active_tasks=AsyncMock(return_value=[task]), is_system_task=Mock(return_value=False))
        scope = definitions('run/scheduled_tasks/schedule_tool.py', {'call_list_schedule_tasks'},
                            {'asyncio': asyncio, 'datetime': dt, 'get_scheduler': lambda **kw: scheduler,
                             'TimezoneHelper': NS(resolve_timezone=resolve), 'logger': Mock()})
        result = await scope['call_list_schedule_tasks'](bot=None, event=NS(user_id=7), config=None)
        self.assertIn('2026-01-01 09:00:00 (Europe/Berlin)', result)
        self.assertTrue(threads)
        self.assertNotIn(main_id, threads)


if __name__ == '__main__':
    unittest.main()
