# -*- coding: utf-8 -*-
import unittest


class TestRewardStatus(unittest.TestCase):
    def test_reward_register_date_has_three_distinct_states(self):
        from lib.db_utils import (
            REWARD_ACTIVE_SQL, REWARD_DELETED_SQL, REWARD_PENDING_SQL,
            rewardActiveSql, rewardState,
        )

        self.assertEqual(REWARD_ACTIVE_SQL, "register_date IS NOT NULL")
        self.assertEqual(REWARD_PENDING_SQL, "register_date = ''")
        self.assertEqual(REWARD_DELETED_SQL, "register_date IS NULL")
        self.assertEqual(rewardActiveSql(), REWARD_ACTIVE_SQL)
        self.assertEqual(rewardActiveSql("r.register_date"), "r.register_date IS NOT NULL")
        self.assertEqual(rewardState(None), "deleted")
        self.assertEqual(rewardState(""), "pending")
        self.assertEqual(rewardState("2026-07-21"), "issued")


if __name__ == "__main__":
    unittest.main()
