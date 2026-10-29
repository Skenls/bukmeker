from __future__ import annotations

import unittest

from app.keyboards import EventCB
from app.utils import clean_title, esc, fmt_gold, fmt_odds, fmt_signed, parse_amount, parse_odds

class UtilsTest(unittest.TestCase):
    def test_esc(self):
        self.assertEqual(esc("<b>&"), "&lt;b&gt;&amp;")

    def test_gold(self):
        self.assertEqual(fmt_gold(1_000_000), "1 000 000")
        self.assertEqual(fmt_signed(-250), "−250")
        self.assertEqual(fmt_signed(0), "+0")

    def test_odds_format(self):
        self.assertEqual(fmt_odds(101), "1.01")
        self.assertEqual(fmt_odds(250), "2.5")
        self.assertEqual(fmt_odds(10_000), "100")
    def test_odds_parse(self):
        self.assertEqual(parse_odds("2,5"), 250)
        self.assertEqual(parse_odds("1.01"), 101)
        self.assertEqual(parse_odds("100.00"), 10_000)
        for bad in ("0.99", "1.234", "101", "abc", "1,2,3"):
            with self.assertRaises(ValueError):
                parse_odds(bad)

    def test_amount_parse(self):
        self.assertEqual(parse_amount("100", 10, 1000), 100)
        for bad in ("9", "1001", "-5", "1 000", "1.5", "abc"):
            with self.assertRaises(ValueError):
                parse_amount(bad, 10, 1000)

    def test_title(self):
        self.assertEqual(clean_title("  hello\u200b   world  "), "hello world")
        with self.assertRaises(ValueError):
            clean_title(" ab ")
        with self.assertRaises(ValueError):
            clean_title("a" * 201)
    def test_callback_roundtrip(self):
        data = EventCB(action="view", event_id=42, offset=7)
        self.assertEqual(EventCB.unpack(data.pack()), data)
        self.assertLessEqual(len(data.pack().encode()), 64)

if __name__ == "__main__":
    unittest.main()
