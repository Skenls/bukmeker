from __future__ import annotations

import unittest

from app.keyboards import EventCB, TransferCB
from app.utils import (
    clean_title,
    esc,
    fmt_gold,
    fmt_odds,
    fmt_signed,
    parse_amount,
    parse_odds,
    parse_transfer_amount,
    validate_recipient_query,
)


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

        tr_data = TransferCB(action="submit", recipient_id=987654321)
        self.assertEqual(TransferCB.unpack(tr_data.pack()), tr_data)
        self.assertLessEqual(len(tr_data.pack().encode()), 64)

    def test_validate_recipient_query(self):
        self.assertEqual(validate_recipient_query("@durov"), "durov")
        self.assertEqual(validate_recipient_query("durov"), "durov")
        self.assertEqual(validate_recipient_query("  123456789  "), "123456789")
        self.assertEqual(validate_recipient_query("@user_123"), "user_123")

        # Injections and invalid formats
        for bad in (
            "",
            "@",
            "ab",  # too short
            "a" * 33,  # too long
            "user; DROP TABLE users;--",
            "user' OR '1'='1",
            "<script>",
            "user-name",  # hyphen not allowed in tg username
            "user name",
            "-12345",
        ):
            with self.assertRaises(ValueError):
                validate_recipient_query(bad)

    def test_parse_transfer_amount(self):
        self.assertEqual(parse_transfer_amount("500", 1000), 500)
        self.assertEqual(parse_transfer_amount("1000", 1000), 1000)
        self.assertEqual(parse_transfer_amount("1", 1000), 1)

        for bad in ("0", "-10", "1001", "1.5", "1,5", "abc", "10 000", "1e5"):
            with self.assertRaises(ValueError):
                parse_transfer_amount(bad, 1000)

if __name__ == "__main__":
    unittest.main()
