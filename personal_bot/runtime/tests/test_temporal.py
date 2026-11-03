import unittest
from datetime import datetime, timedelta, timezone

from muse_ext.temporal import parse_due, resolve_query

BJ = timezone(timedelta(hours=8))
NOW = datetime(2026, 11, 3, 8, 30, tzinfo=BJ)


class TemporalTests(unittest.TestCase):
    def test_yesterday_morning_retrieves_calendar_window(self):
        r = resolve_query('昨天早上我跟你说了什么？', NOW)
        self.assertEqual(r['start'], datetime(2026, 11, 2, 5, tzinfo=BJ).timestamp())
        self.assertEqual(r['end'], datetime(2026, 11, 2, 12, tzinfo=BJ).timestamp())
        self.assertEqual(r['query'], '')

    def test_keyword_is_retained_but_time_words_removed(self):
        r = resolve_query('昨天晚上说的蓝鲸', NOW)
        self.assertEqual(r['query'], '蓝鲸')
        self.assertEqual(r['start'], datetime(2026, 11, 2, 18, tzinfo=BJ).timestamp())

    def test_previous_week_is_monday_to_monday(self):
        r = resolve_query('上周的运动计划', NOW)
        self.assertEqual(r['start'], datetime(2026, 10, 26, tzinfo=BJ).timestamp())
        self.assertEqual(r['end'], datetime(2026, 11, 2, tzinfo=BJ).timestamp())
        self.assertEqual(r['query'], '运动计划')

    def test_relative_query_crosses_beijing_midnight(self):
        r = resolve_query('昨天发生了什么', datetime(2026, 11, 3, 0, 1, tzinfo=BJ))
        self.assertEqual(r['start'], datetime(2026, 11, 2, tzinfo=BJ).timestamp())
        self.assertEqual(r['end'], datetime(2026, 11, 3, tzinfo=BJ).timestamp())

    def test_explicit_date_and_month_boundary(self):
        r = resolve_query('2026年10月31日下午的讨论', NOW)
        self.assertEqual(r['start'], datetime(2026, 10, 31, 12, tzinfo=BJ).timestamp())
        self.assertEqual(r['end'], datetime(2026, 10, 31, 18, tzinfo=BJ).timestamp())
        prev = resolve_query('上个月的记录', NOW)
        self.assertEqual(prev['start'], datetime(2026, 10, 1, tzinfo=BJ).timestamp())
        self.assertEqual(prev['end'], datetime(2026, 11, 1, tzinfo=BJ).timestamp())

    def test_non_temporal_input_is_not_rewritten(self):
        self.assertIsNone(resolve_query('我喜欢蓝鲸', NOW))

    def test_due_tomorrow_afternoon(self):
        r = parse_due('明天下午三点提醒我交作业', NOW)
        self.assertTrue(r['ok'])
        self.assertEqual(r['due_at'], datetime(2026, 11, 4, 15, tzinfo=BJ).timestamp())
        self.assertEqual(r['timezone'], 'Asia/Shanghai')

    def test_ambiguous_three_oclock_requests_clarification(self):
        r = parse_due('明天三点叫我', NOW)
        self.assertFalse(r['ok'])
        self.assertTrue(r['needs_clarification'])

    def test_past_due_is_not_silently_moved_to_tomorrow(self):
        r = parse_due('今天上午八点提醒我', NOW)
        self.assertFalse(r['ok'])
        self.assertEqual(r['reason'], 'time_in_past')

    def test_relative_minutes_and_chinese_number(self):
        r = parse_due('十五分钟后提醒我喝水', NOW)
        self.assertEqual(r['due_at'], (NOW+timedelta(minutes=15)).timestamp())
        r = parse_due('两小时后提醒我', NOW)
        self.assertEqual(r['due_at'], (NOW+timedelta(hours=2)).timestamp())

    def test_explicit_colon_clock_and_next_week(self):
        r = parse_due('明天03:00提醒我', NOW)
        self.assertEqual(r['due_at'], datetime(2026, 11, 4, 3, tzinfo=BJ).timestamp())
        r = parse_due('下周五下午三点提醒我', NOW)
        self.assertEqual(r['due_at'], datetime(2026, 11, 13, 15, tzinfo=BJ).timestamp())

    def test_invalid_date_and_unknown_timezone_need_clarification(self):
        self.assertFalse(parse_due('2026年2月30日下午三点', NOW)['ok'])
        self.assertFalse(parse_due('明天下午三点纽约时间', NOW)['ok'])

    def test_midnight_after_tonight_is_next_date(self):
        r = parse_due('今晚十二点提醒我', NOW)
        self.assertEqual(r['due_at'], datetime(2026, 11, 4, 0, tzinfo=BJ).timestamp())


if __name__ == '__main__':
    unittest.main()

class TemporalRegressionTests(unittest.TestCase):
    def test_ordinary_zhou_words_are_not_calendar_expressions(self):
        self.assertIsNone(resolve_query('周杰伦的歌',NOW))
        self.assertIsNone(resolve_query('记忆巩固周期',NOW))
        self.assertIsNotNone(resolve_query('周五的安排',NOW))
    def test_dawn_twelve_is_midnight_and_contradictions_rejected(self):
        r=parse_due('明天凌晨十二点提醒我喝水',NOW)
        self.assertEqual(r['due_at'],datetime(2026,11,4,0,tzinfo=BJ).timestamp())
        self.assertFalse(parse_due('明天凌晨十点提醒我',NOW)['ok'])
        self.assertFalse(parse_due('明天上午十五点提醒我',NOW)['ok'])
