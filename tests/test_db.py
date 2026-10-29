from __future__ import annotations

import asyncio
import os
import tempfile
import unittest

from app.db import ActionError, Database


class DatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Database(
            os.path.join(self._tmp.name, "test.db"),
            start_balance=1000,
            min_bet=10,
            max_pending=3,
        )
        await self.db.connect()
        self.addAsyncCleanup(self._cleanup)

        for user_id in (1, 2, 3, 4):
            await self.db.ensure_user(user_id, f"user{user_id}", f"User {user_id}")

        self._seq = 0

    async def _cleanup(self) -> None:
        await self.db.close()
        self._tmp.cleanup()

    async def _approved_event(self, proposer_id: int = 1, odds_x100: int = 250) -> int:
        self._seq += 1
        event_id = await self.db.create_event(
            proposer_id, f"Test event {self._seq}", odds_x100
        )
        await self.db.review_event(event_id, True)
        return event_id

    async def test_win_payout_and_second_resolve_fails(self) -> None:
        event_id = await self._approved_event()

        bet = await self.db.place_bet(2, event_id, 100)
        self.assertEqual(bet["payout"], 250)
        self.assertEqual(bet["balance"], 900)

        event, notifications = await self.db.resolve_event(event_id, "won", 4)
        self.assertEqual(event["status"], "won")
        self.assertEqual(
            notifications, [{"user_id": 2, "amount": 100, "payout": 250}]
        )

        user = await self.db.get_user(2)
        self.assertEqual(user["balance"], 1150)
        saved_bet = await self.db.get_user_bet(event_id, 2)
        self.assertEqual(saved_bet["status"], "won")
        self.assertEqual(saved_bet["payout"], 250)

        with self.assertRaises(ActionError):
            await self.db.resolve_event(event_id, "won", 4)

    async def test_bet_guards(self) -> None:
        event_id = await self._approved_event()

        with self.assertRaises(ActionError):
            await self.db.place_bet(1, event_id, 100)  # proposer's own event

        with self.assertRaises(ActionError):
            await self.db.place_bet(2, event_id, 2000)  # insufficient balance

        with self.assertRaises(ActionError):
            await self.db.place_bet(3, event_id, 9)  # below minimum

        await self.db.place_bet(2, event_id, 100)
        with self.assertRaises(ActionError):
            await self.db.place_bet(2, event_id, 100)  # double bet

        self.assertEqual((await self.db.get_user(2))["balance"], 900)
        self.assertEqual((await self.db.get_user(3))["balance"], 1000)

    async def test_cancel_refund_and_lost_outcome(self) -> None:
        cancel_event = await self._approved_event()
        await self.db.place_bet(2, cancel_event, 100)
        self.assertEqual((await self.db.get_user(2))["balance"], 900)

        event, notifications = await self.db.resolve_event(cancel_event, "cancelled", 4)
        self.assertEqual(event["status"], "cancelled")
        self.assertEqual(
            notifications, [{"user_id": 2, "amount": 100, "payout": 100}]
        )
        self.assertEqual((await self.db.get_user(2))["balance"], 1000)
        refunded = await self.db.get_user_bet(cancel_event, 2)
        self.assertEqual(refunded["status"], "refunded")
        self.assertEqual(refunded["payout"], 100)

        lost_event = await self._approved_event()
        await self.db.place_bet(3, lost_event, 200)
        event, notifications = await self.db.resolve_event(lost_event, "lost", 4)
        self.assertEqual(event["status"], "lost")
        self.assertEqual(notifications, [{"user_id": 3, "amount": 200, "payout": 0}])
        self.assertEqual((await self.db.get_user(3))["balance"], 800)
        lost = await self.db.get_user_bet(lost_event, 3)
        self.assertEqual(lost["status"], "lost")
        self.assertEqual(lost["payout"], 0)

    async def test_concurrent_bets_only_one_succeeds(self) -> None:
        event_id = await self._approved_event()

        results = await asyncio.gather(
            self.db.place_bet(2, event_id, 600),
            self.db.place_bet(2, event_id, 600),
            return_exceptions=True,
        )

        successful = [result for result in results if isinstance(result, dict)]
        failed = [result for result in results if isinstance(result, ActionError)]
        self.assertEqual(len(successful), 1)
        self.assertEqual(len(failed), 1)

        self.assertEqual(successful[0]["balance"], 400)
        self.assertEqual((await self.db.get_user(2))["balance"], 400)

        event = await self.db.get_event(event_id)
        self.assertEqual(event["bet_count"], 1)
        bet = await self.db.get_user_bet(event_id, 2)
        self.assertEqual(bet["status"], "active")
        self.assertEqual(bet["amount"], 600)

    async def test_pending_proposal_limit_then_approve_one(self) -> None:
        event_ids = []
        for index in range(3):
            event_ids.append(
                await self.db.create_event(1, f"Pending event {index}", 200)
            )

        with self.assertRaises(ActionError):
            await self.db.create_event(1, "One too many", 200)

        self.assertEqual(await self.db.count_events("pending"), 3)

        await self.db.review_event(event_ids[0], True)
        await self.db.create_event(1, "After approval", 200)

        self.assertEqual(await self.db.count_events("pending"), 3)
        self.assertEqual(await self.db.count_events("open"), 1)

    async def test_malicious_title_is_stored_and_users_table_survives(self) -> None:
        title = "'); DROP TABLE users;--"
        event_id = await self.db.create_event(1, title, 200)

        event = await self.db.get_event(event_id)
        self.assertEqual(event["title"], title)

        await self.db.ensure_user(99, "newuser", "New User")
        user = await self.db.get_user(99)
        self.assertEqual(user["balance"], 1000)
        self.assertEqual((await self.db.get_user(1))["balance"], 1000)

    async def test_claim_admin_and_stats_after_win(self) -> None:
        self.assertTrue(await self.db.claim_admin(4))
        self.assertFalse(await self.db.claim_admin(3))
        self.assertTrue(await self.db.is_claimed_admin(4))
        self.assertFalse(await self.db.is_claimed_admin(3))

        event_id = await self._approved_event()
        await self.db.place_bet(2, event_id, 100)
        await self.db.resolve_event(event_id, "won", 4)

        stats = await self.db.stats_for_user(2)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["won"], 1)
        self.assertEqual(stats["staked"], 100)
        self.assertEqual(stats["net"], 150)


if __name__ == "__main__":
    unittest.main()
