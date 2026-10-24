"""Offline regression tests for city resolution and daylight-saving schedules.

Run from the repository root with ``python -m unittest discover -s tests -v``.
Load the helper directly so these tests do not import the bot and its services.
"""

import datetime
import importlib.util
from pathlib import Path
import types
import unittest
from unittest import mock

from dateutil import tz


HELPER_PATH = (
    Path(__file__).resolve().parents[1]
    / "framework_common"
    / "schedule_service"
    / "timezone_helper.py"
)
SPEC = importlib.util.spec_from_file_location("timezone_helper_under_test", HELPER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Cannot load timezone helper: {HELPER_PATH}")
timezone_helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(timezone_helper)
TimezoneHelper = timezone_helper.TimezoneHelper
UTC = datetime.timezone.utc


class TimezoneHelperTests(unittest.TestCase):
    def setUp(self):
        # Unknown cities must stay offline and must never touch the bot's DB.
        self.cache_lookup = self._patch("_get_cached_tz", return_value=None)
        self.cache_write = self._patch("_save_cached_tz")
        self.remote_lookup = self._patch("_query_remote_geocoding_tz", return_value=None)

    def _patch(self, name, **kwargs):
        patcher = mock.patch.object(TimezoneHelper, name, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def freeze_now(self, instant):
        """Freeze only the helper's datetime module, leaving test clocks intact."""
        class FrozenDatetime(datetime.datetime):
            @classmethod
            def now(cls, zone=None):
                if zone is None:
                    return instant.replace(tzinfo=None)
                return instant.astimezone(zone)

        frozen_module = types.ModuleType("datetime")
        frozen_module.__dict__.update(datetime.__dict__)
        frozen_module.datetime = FrozenDatetime
        return mock.patch.object(timezone_helper, "datetime", frozen_module)

    def assert_instant(self, actual, expected_utc):
        self.assertIsNotNone(actual.tzinfo)
        self.assertEqual(actual.astimezone(UTC), expected_utc)
        self.assertEqual(actual.utcoffset(), datetime.timedelta(hours=8))

    def next_run(self, now_utc, hour=9, minute=0, city="Europe/Berlin", weekdays=None):
        return TimezoneHelper.compute_next_bot_run_time(
            hour, minute, city, weekdays=weekdays, from_bot_dt=now_utc
        )

    def test_stuttgart_aliases_resolve_offline_to_berlin(self):
        for query in ("Stuttgart", "斯图加特", "德国Stuttgart", "Stuttgart, Germany"):
            with self.subTest(query=query):
                zone, name, _ = TimezoneHelper.resolve_timezone(query)
                self.assertEqual(name, "Europe/Berlin")
                winter = datetime.datetime(2026, 1, 15, tzinfo=zone)
                summer = datetime.datetime(2026, 7, 15, tzinfo=zone)
                self.assertEqual(winter.utcoffset(), datetime.timedelta(hours=1))
                self.assertEqual(summer.utcoffset(), datetime.timedelta(hours=2))
        self.cache_lookup.assert_not_called()
        self.remote_lookup.assert_not_called()
        self.cache_write.assert_not_called()

    def test_explicit_iana_name_precedes_city_substrings(self):
        for name in ("Europe/Bratislava", "Europe/Paris", "Asia/Kuala_Lumpur"):
            with self.subTest(name=name):
                zone, resolved_name, _ = TimezoneHelper.resolve_timezone(name)
                self.assertEqual(resolved_name, name)
                self.assertEqual(
                    datetime.datetime(2026, 1, 15, tzinfo=zone).utcoffset(),
                    datetime.datetime(2026, 1, 15, tzinfo=tz.gettz(name)).utcoffset(),
                )
        self.remote_lookup.assert_not_called()

    def test_english_city_names_match_whole_words(self):
        known = {
            "Dallas": "America/Chicago",
            "Dallas, Texas": "America/Chicago",
            "LA, USA": "America/Los_Angeles",
            "Berlin, Germany": "Europe/Berlin",
        }
        for query, name in known.items():
            with self.subTest(query=query):
                self.assertEqual(TimezoneHelper.resolve_timezone(query)[1], name)

    def test_unrelated_words_do_not_match_short_city_names(self):
        # "la", "rome", "london", and "stuttgart" are not arbitrary substrings.
        for query in ("plaza", "Romeo", "Londonderry", "Stuttgarter"):
            with self.subTest(query=query):
                self.assertEqual(
                    TimezoneHelper.resolve_timezone(query)[1], "Asia/Shanghai"
                )
        self.assertEqual(self.remote_lookup.call_count, 4)
        self.cache_write.assert_not_called()

    def test_zero_utc_offset_is_not_replaced_with_shanghai_offset(self):
        with self.freeze_now(datetime.datetime(2026, 1, 15, 12, tzinfo=UTC)):
            for query in ("London", "Europe/London", "UTC", "GMT"):
                with self.subTest(query=query):
                    zone, _, offset = TimezoneHelper.resolve_timezone(query)
                    self.assertEqual(offset, 0.0)
                    self.assertEqual(
                        datetime.datetime(2026, 1, 15, tzinfo=zone).utcoffset(),
                        datetime.timedelta(0),
                    )

    def test_negative_fractional_offsets_agree_with_tzinfo(self):
        for query, hours in (("UTC-03:30", -3.5), ("-00:30", -0.5)):
            with self.subTest(query=query):
                zone, _, offset = TimezoneHelper.resolve_timezone(query)
                self.assertEqual(offset, hours)
                self.assertEqual(
                    datetime.datetime(2026, 1, 15, tzinfo=zone).utcoffset(),
                    datetime.timedelta(hours=hours),
                )

    def test_resolved_offset_tracks_winter_and_summer(self):
        zones = {
            "Europe/Berlin": (1, 2),
            "Europe/London": (0, 1),
            "Europe/Paris": (1, 2),
            "Europe/Helsinki": (2, 3),
        }
        for name, offsets in zones.items():
            for month, expected in zip((1, 7), offsets):
                with self.subTest(name=name, month=month):
                    instant = datetime.datetime(2026, month, 15, 12, tzinfo=UTC)
                    with self.freeze_now(instant):
                        zone, resolved_name, offset = TimezoneHelper.resolve_timezone(name)
                    self.assertEqual(resolved_name, name)
                    self.assertEqual(offset, expected)
                    self.assertEqual(
                        instant.astimezone(zone).utcoffset(),
                        datetime.timedelta(hours=expected),
                    )

    def test_2040_resolved_european_offsets_use_future_rules(self):
        # TZif transition tables may end in 2037; the POSIX tail must continue
        # to supply the zone's recurring rules after the final stored transition.
        zones = {
            "Europe/Berlin": (1, 2),
            "Europe/London": (0, 1),
            "Europe/Paris": (1, 2),
            "Europe/Helsinki": (2, 3),
        }
        for name, offsets in zones.items():
            for month, expected in zip((1, 7), offsets):
                with self.subTest(name=name, month=month):
                    instant = datetime.datetime(2040, month, 15, 12, tzinfo=UTC)
                    with self.freeze_now(instant):
                        zone, resolved_name, offset = TimezoneHelper.resolve_timezone(name)
                    self.assertEqual(resolved_name, name)
                    self.assertEqual(offset, expected)
                    self.assertEqual(
                        instant.astimezone(zone).utcoffset(),
                        datetime.timedelta(hours=expected),
                    )

    def test_2040_daily_schedule_uses_future_dst_rules(self):
        zones = {
            "Europe/Berlin": (8, 7),
            "Europe/London": (9, 8),
            "Europe/Paris": (8, 7),
            "Europe/Helsinki": (7, 6),
        }
        # Scheduling a future summer date must not reuse the present offset.
        with self.freeze_now(datetime.datetime(2026, 1, 15, tzinfo=UTC)):
            for name, utc_hours in zones.items():
                for month, utc_hour in zip((1, 7), utc_hours):
                    with self.subTest(name=name, month=month):
                        now = datetime.datetime(2040, month, 15, tzinfo=UTC)
                        self.assert_instant(
                            self.next_run(now, city=name),
                            datetime.datetime(2040, month, 15, utc_hour, tzinfo=UTC),
                        )

    def test_european_spring_transition_occurs_at_same_utc_instant(self):
        before = datetime.datetime(2026, 3, 29, 0, 59, tzinfo=UTC)
        after = datetime.datetime(2026, 3, 29, 1, 0, tzinfo=UTC)
        for name, winter_offset in (
            ("Europe/Lisbon", 0),
            ("Europe/Berlin", 1),
            ("Europe/Helsinki", 2),
        ):
            with self.subTest(name=name):
                local_before = TimezoneHelper.get_user_local_time(name, base_time=before)
                local_after = TimezoneHelper.get_user_local_time(name, base_time=after)
                self.assertEqual(
                    local_before.utcoffset(), datetime.timedelta(hours=winter_offset)
                )
                self.assertEqual(
                    local_after.utcoffset(), datetime.timedelta(hours=winter_offset + 1)
                )
                self.assertEqual((local_before.hour, local_before.minute), (winter_offset, 59))
                self.assertEqual((local_after.hour, local_after.minute), (winter_offset + 2, 0))
                self.assertEqual(local_before.astimezone(UTC), before)
                self.assertEqual(local_after.astimezone(UTC), after)

    def test_european_autumn_transition_occurs_at_same_utc_instant(self):
        before = datetime.datetime(2026, 10, 25, 0, 59, tzinfo=UTC)
        after = datetime.datetime(2026, 10, 25, 1, 0, tzinfo=UTC)
        for name, winter_offset in (
            ("Europe/Lisbon", 0),
            ("Europe/Berlin", 1),
            ("Europe/Helsinki", 2),
        ):
            with self.subTest(name=name):
                local_before = TimezoneHelper.get_user_local_time(name, base_time=before)
                local_after = TimezoneHelper.get_user_local_time(name, base_time=after)
                self.assertEqual(
                    local_before.utcoffset(), datetime.timedelta(hours=winter_offset + 1)
                )
                self.assertEqual(
                    local_after.utcoffset(), datetime.timedelta(hours=winter_offset)
                )
                self.assertEqual(
                    (local_before.hour, local_before.minute), (winter_offset + 1, 59)
                )
                self.assertEqual((local_after.hour, local_after.minute), (winter_offset + 1, 0))
                self.assertEqual(local_before.fold, 0)
                self.assertEqual(local_after.fold, 1)
                self.assertEqual(local_before.astimezone(UTC), before)
                self.assertEqual(local_after.astimezone(UTC), after)

    def test_moscow_and_istanbul_do_not_follow_eu_dst_changes(self):
        instants = (
            datetime.datetime(2026, 3, 29, 0, 59, tzinfo=UTC),
            datetime.datetime(2026, 3, 29, 1, 0, tzinfo=UTC),
            datetime.datetime(2026, 10, 25, 0, 59, tzinfo=UTC),
            datetime.datetime(2026, 10, 25, 1, 0, tzinfo=UTC),
            datetime.datetime(2040, 1, 15, 12, tzinfo=UTC),
            datetime.datetime(2040, 7, 15, 12, tzinfo=UTC),
        )
        for name in ("Europe/Moscow", "Europe/Istanbul"):
            for instant in instants:
                with self.subTest(name=name, instant=instant):
                    local = TimezoneHelper.get_user_local_time(name, base_time=instant)
                    self.assertEqual(local.utcoffset(), datetime.timedelta(hours=3))
                    self.assertEqual(local.dst(), datetime.timedelta(0))
                    self.assertEqual(local.astimezone(UTC), instant)

    def test_local_time_uses_date_specific_offset(self):
        for month, hour in ((1, 13), (7, 14)):
            with self.subTest(month=month):
                base = datetime.datetime(2026, month, 15, 12, tzinfo=UTC)
                local = TimezoneHelper.get_user_local_time("Stuttgart", base_time=base)
                self.assertEqual(local.hour, hour)
                self.assertEqual(local.astimezone(UTC), base)

    def test_naive_base_time_retains_bot_timezone_convention(self):
        local = TimezoneHelper.get_user_local_time(
            "Stuttgart", base_time=datetime.datetime(2026, 1, 15, 12)
        )
        self.assertEqual(local.hour, 5)
        self.assertEqual(
            local.astimezone(UTC), datetime.datetime(2026, 1, 15, 4, tzinfo=UTC)
        )

    def test_normalize_rejects_naive_datetime(self):
        with self.assertRaises(ValueError):
            TimezoneHelper.normalize_local_datetime(datetime.datetime(2026, 3, 29, 2, 30))

    def test_normalize_spring_gap_moves_forward_by_gap(self):
        missing = datetime.datetime(2026, 3, 29, 2, 30, tzinfo=tz.gettz("Europe/Berlin"))
        normalized = TimezoneHelper.normalize_local_datetime(missing)
        self.assertTrue(tz.datetime_exists(normalized))
        self.assertEqual((normalized.hour, normalized.minute), (3, 30))
        self.assertEqual(
            normalized.astimezone(UTC), datetime.datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
        )

    def test_normalize_autumn_overlap_selects_first_occurrence(self):
        repeated = datetime.datetime(
            2026, 10, 25, 2, 30, tzinfo=tz.gettz("Europe/Berlin"), fold=1
        )
        normalized = TimezoneHelper.normalize_local_datetime(repeated)
        self.assertEqual(normalized.fold, 0)
        self.assertEqual(
            normalized.astimezone(UTC), datetime.datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
        )

    def test_normalize_preserves_valid_local_time(self):
        local = datetime.datetime(2026, 7, 15, 9, 20, tzinfo=tz.gettz("Europe/Berlin"))
        self.assertEqual(TimezoneHelper.normalize_local_datetime(local), local)

    def test_europe_daily_schedules_use_target_date_offset(self):
        zones = {
            "Stuttgart": (8, 7),
            "Europe/London": (9, 8),
            "Europe/Paris": (8, 7),
            "Europe/Helsinki": (7, 6),
        }
        # The real clock is deliberately frozen in winter: July scheduling must
        # still use July's offset rather than the offset returned by resolution.
        with self.freeze_now(datetime.datetime(2026, 1, 15, tzinfo=UTC)):
            for city, utc_hours in zones.items():
                for month, utc_hour in zip((1, 7), utc_hours):
                    with self.subTest(city=city, month=month):
                        now = datetime.datetime(2026, month, 15, tzinfo=UTC)
                        self.assert_instant(
                            self.next_run(now, city=city),
                            datetime.datetime(2026, month, 15, utc_hour, tzinfo=UTC),
                        )

    def test_daily_schedule_crosses_spring_transition(self):
        now = datetime.datetime(2026, 3, 28, 8, 30, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now), datetime.datetime(2026, 3, 29, 7, tzinfo=UTC)
        )

    def test_daily_schedule_crosses_autumn_transition(self):
        now = datetime.datetime(2026, 10, 24, 7, 30, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now), datetime.datetime(2026, 10, 25, 8, tzinfo=UTC)
        )

    def test_missing_spring_time_runs_at_0330(self):
        now = datetime.datetime(2026, 3, 29, 0, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30),
            datetime.datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        )

    def test_shifted_spring_time_can_still_be_upcoming(self):
        # At 03:15 local, nominal 02:30 is past but its normalized 03:30 is future.
        now = datetime.datetime(2026, 3, 29, 1, 15, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30),
            datetime.datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        )

    def test_spring_gap_after_shifted_time_moves_to_next_day(self):
        now = datetime.datetime(2026, 3, 29, 1, 45, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30),
            datetime.datetime(2026, 3, 30, 0, 30, tzinfo=UTC),
        )

    def test_autumn_ambiguous_time_runs_on_first_occurrence(self):
        now = datetime.datetime(2026, 10, 25, 0, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30),
            datetime.datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
        )

    def test_autumn_does_not_run_again_on_second_occurrence(self):
        now = datetime.datetime(2026, 10, 25, 0, 45, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30),
            datetime.datetime(2026, 10, 26, 1, 30, tzinfo=UTC),
        )

    def test_second_overlap_hour_does_not_return_past_instant(self):
        # 02:15 fold=1 occurs AFTER 02:30 fold=0 on the actual UTC timeline.
        now = datetime.datetime(2026, 10, 25, 1, 15, tzinfo=UTC)
        result = self.next_run(now, hour=2, minute=30)
        self.assertGreater(result.astimezone(UTC), now)
        self.assert_instant(result, datetime.datetime(2026, 10, 26, 1, 30, tzinfo=UTC))

    def test_current_candidate_is_strictly_excluded(self):
        now = datetime.datetime(2026, 1, 15, 8, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now), datetime.datetime(2026, 1, 16, 8, tzinfo=UTC)
        )

    def test_weekday_filter_uses_users_local_date_across_dst(self):
        now = datetime.datetime(2026, 3, 28, 8, 30, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, weekdays=[0]),
            datetime.datetime(2026, 3, 30, 7, tzinfo=UTC),
        )

    def test_weekly_spring_gap_preserves_local_weekday(self):
        now = datetime.datetime(2026, 3, 28, 12, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30, weekdays=[6]),
            datetime.datetime(2026, 3, 29, 1, 30, tzinfo=UTC),
        )

    def test_weekly_overlap_after_first_occurrence_waits_one_week(self):
        now = datetime.datetime(2026, 10, 25, 1, 15, tzinfo=UTC)
        self.assert_instant(
            self.next_run(now, hour=2, minute=30, weekdays=[6]),
            datetime.datetime(2026, 11, 1, 1, 30, tzinfo=UTC),
        )

    def test_shanghai_schedule_remains_compatible(self):
        now = datetime.datetime(2026, 3, 29, 0, tzinfo=UTC)
        for city in (None, "上海", "Asia/Shanghai", "东八区", "UTC+8"):
            with self.subTest(city=city):
                self.assert_instant(
                    self.next_run(now, city=city),
                    datetime.datetime(2026, 3, 29, 1, tzinfo=UTC),
                )

    def test_naive_schedule_origin_uses_shanghai(self):
        now = datetime.datetime(2026, 1, 15, 12)
        self.assert_instant(
            self.next_run(now, city="Stuttgart"),
            datetime.datetime(2026, 1, 15, 8, tzinfo=UTC),
        )


if __name__ == "__main__":
    unittest.main()
