"""敘獎由回收筒還原後的跨頁刷新通知。"""
import unittest

from tabs.tab_settings import TabSettings


class _Browse:
    def __init__(self):
        self._pending_reload_keys = None

    def _forceReload(self, _key):
        pass


class _Reward:
    def __init__(self):
        self.reward_data_dirty = False
        self._session_doc_ids = ["7"]


class _Manager:
    def __init__(self, tabs):
        self.tabs = tabs


class TestRewardRestoreRefresh(unittest.TestCase):
    def test_restore_marks_browse_and_reward_without_adding_session_id(self):
        settings = TabSettings.__new__(TabSettings)
        browse = _Browse()
        reward = _Reward()
        settings._manager = _Manager({"browse": browse, "reward": reward})

        settings._flagSiblingReload("reward")

        self.assertEqual(browse._pending_reload_keys, {"reward"})
        self.assertTrue(reward.reward_data_dirty)
        self.assertEqual(reward._session_doc_ids, ["7"])


if __name__ == "__main__":
    unittest.main()
