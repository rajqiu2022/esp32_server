from datetime import datetime, timezone
import unittest

from server.live_context import with_live_context


class LiveContextTests(unittest.TestCase):
    def test_china_midnight_and_history_cannot_freeze_time(self):
        history = [{"role": "system", "content": "Friendly"},
                   {"role": "assistant", "content": "无法获取实时日期"}]
        before = with_live_context(history, "example", datetime(2026, 10, 15, 15, 59, tzinfo=timezone.utc))
        after = with_live_context(history, "example", datetime(2026, 10, 15, 16, 1, tzinfo=timezone.utc))
        self.assertIn("2026年10月15日 23:59:00", before[0]["content"])
        self.assertIn("2026年10月16日 00:01:00，星期五", after[0]["content"])
        self.assertEqual(history[0]["content"], "Friendly")
        self.assertEqual(after[1], history[1])
        self.assertIn("example", after[0]["content"])

    def test_context_added_without_existing_system_message(self):
        result = with_live_context([{"role": "user", "content": "今天几号"}], "example")
        self.assertEqual(result[0]["role"], "system")
        self.assertEqual(result[1]["content"], "今天几号")
        self.assertIn("尚未配置网页搜索工具", result[0]["content"])
