# -*- coding: utf-8 -*-
import sqlite3
import unittest

from lib.db_schema import applySchema
from lib.db_utils import (
    REWARD_ACTIVE_SQL,
    REWARD_DELETED_SQL,
    REWARD_PENDING_SQL,
    rewardActiveSql,
    rewardState,
)


class TestRewardStatus(unittest.TestCase):
    def test_reward_register_date_has_three_distinct_states(self):
        conn = sqlite3.connect(":memory:")
        self.addCleanup(conn.close)
        applySchema(conn)
        rows = [
            ("R-NULL", "2026-07-22", None, None, "deleted", ""),
            ("R-PENDING", "2026-07-22", "", None, "pending", ""),
            ("R-ISSUED", "2026-07-22", "2026-07-23", "P01", "issued", ""),
        ]
        conn.executemany(
            "INSERT INTO Document_Reward "
            "(doc_id,create_date,register_date,sender_id,reason,recipients) "
            "VALUES(?,?,?,?,?,?)",
            rows,
        )
        conn.commit()

        def ids_where(where_clause):
            return {
                row[0] for row in conn.execute(
                    f"SELECT doc_id FROM Document_Reward WHERE {where_clause}"
                )
            }

        active_ids = ids_where(REWARD_ACTIVE_SQL)
        active_alias_ids = {
            row[0] for row in conn.execute(
                "SELECT r.doc_id FROM Document_Reward r WHERE "
                + rewardActiveSql("r.register_date")
            )
        }
        pending_ids = ids_where(REWARD_PENDING_SQL)
        deleted_ids = ids_where(REWARD_DELETED_SQL)
        states = {
            doc_id: rewardState(register_date)
            for doc_id, register_date in conn.execute(
                "SELECT doc_id, register_date FROM Document_Reward"
            )
        }

        self.assertEqual(active_ids, {"R-PENDING", "R-ISSUED"})
        self.assertEqual(active_alias_ids, active_ids)
        self.assertEqual(pending_ids, {"R-PENDING"})
        self.assertEqual(deleted_ids, {"R-NULL"})
        self.assertEqual(states, {
            "R-NULL": "deleted",
            "R-PENDING": "pending",
            "R-ISSUED": "issued",
        })


if __name__ == "__main__":
    unittest.main()
