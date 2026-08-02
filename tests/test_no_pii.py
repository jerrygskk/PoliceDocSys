"""個資防呆：push 前確認 git 追蹤內容未命中本機已知 denylist。

設計重點：
  - 掃描清單只來自 ``git ls-files``，不含 untracked／ignored（如正式 dbfile.db）。
    tracked path 依序讀安全工作樹、index、HEAD；工作樹 path 的 target 與各層 parent
    必須都留在 repo 內，不跟隨外部 symlink／junction。
  - 另在專案 ``.tmp`` 產一份乾淨空殼（tools/gen_shell_db）掃其位元組，驗證
    db_seed 未命中 denylist。
  - 比對清單 tests/pii_denylist.local.txt 為本機檔（已 gitignore，不入庫，
    才不會把真名又帶進 repo）；清單不存在或有效項目為空時明確 skip。
  - 命中即 fail，並列出檔名與名字，提醒「替換後才能 push」。

通過只代表未命中本機已知 denylist，不得宣稱候選姓名已證明不對應真人。

執行：專案根目錄下 `python -m unittest tests.test_no_pii`
"""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DENYLIST = os.path.join(_ROOT, "tests", "pii_denylist.local.txt")
# 只掃會帶字串個資的文字類追蹤檔；二進位 dbfile.db 另以 blob bytes 掃。
_TEXT_EXT = (".py", ".md", ".txt", ".ui", ".qrc", ".sql", ".json")


class TestScreenshotSeedCandidate(unittest.TestCase):
    """公開截圖 seed 必須從 tools 建立完整、自然的候選資料庫。"""

    def test_cli_builds_natural_candidate_database_from_repo_root(self):
        script = Path(_ROOT) / "tools" / "seed_screenshot_data.py"
        self.assertTrue(script.exists(), f"截圖 seed 工具不在預期路徑：{script}")

        temp_root = Path(_ROOT) / ".tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="screenshot-seed-test-", dir=temp_root
        ) as temp_dir:
            output = Path(temp_dir) / "candidate.db"
            result = subprocess.run(
                [sys.executable, str(script), str(output)],
                cwd=_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("待維護者對照真實名單核准", result.stdout)

            conn = sqlite3.connect(output)
            try:
                schema_names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type IN ('table','view')"
                    )
                }
                self.assertTrue(
                    {
                        "Document_Task",
                        "Document_Criminal",
                        "Document_General",
                        "Document_Reward",
                        "Document_Ticket",
                        "View_Task_Full",
                        "View_Criminal_Full",
                        "View_General_Full",
                        "Document_Ticket_Full",
                    }.issubset(schema_names)
                )
                personnel = conn.execute(
                    "SELECT staff_id,staff_name FROM Ref_Personnel "
                    "ORDER BY sort_order"
                ).fetchall()
                self.assertEqual(
                    personnel,
                    [
                        ("P01", "王小明"),
                        ("P02", "李小華"),
                        ("P03", "陳大華"),
                        ("P04", "林小美"),
                        ("P05", "張大同"),
                        ("P06", "吳小芳"),
                    ],
                )
                subjects = [
                    row[0]
                    for row in conn.execute(
                        "SELECT subject FROM Document_Task "
                        "WHERE subject IS NOT NULL ORDER BY CAST(doc_id AS INTEGER)"
                    )
                ]
                self.assertTrue(subjects)
                self.assertTrue(subjects[0].startswith("請各組彙整本月社區治安座談會"))
                self.assertFalse(
                    any(
                        marker in subject
                        for subject in subjects
                        for marker in ("測試甲", "測試乙", "【展示資料】", "【測試資料】")
                    )
                )
            finally:
                conn.close()


class TestTrackedWorktreeScanning(unittest.TestCase):
    """以隔離 git repo 驗證 tracked 工作樹的掃描邊界。"""

    DENIED = "禁止姓名"

    def setUp(self):
        temp_root = Path(_ROOT) / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self._temp = tempfile.TemporaryDirectory(
            prefix="pii-git-test-", dir=temp_root
        )
        self.repo = Path(self._temp.name)
        self._git("init")
        self._git("config", "user.email", "pii-test@example.invalid")
        self._git("config", "user.name", "PII Test")

    def tearDown(self):
        self._temp.cleanup()

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _commit_file(self, relative: str, content: str):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self._git("add", relative)
        self._git("commit", "-m", "test fixture")
        return path

    def _scan(self):
        scanner = globals().get("_scan_tracked_text")
        self.assertIsNotNone(scanner, "尚未提供 tracked 工作樹掃描介面")
        return scanner(self.repo, [self.DENIED])

    def test_tracked_unstaged_modification_is_scanned(self):
        path = self._commit_file("tracked.txt", "乾淨內容")
        path.write_text(self.DENIED, encoding="utf-8")
        self.assertEqual(self._scan(), [f"tracked.txt：{self.DENIED}"])

    def test_staged_new_file_is_scanned(self):
        self._commit_file("baseline.txt", "乾淨內容")
        staged = self.repo / "staged.txt"
        staged.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "staged.txt")
        self.assertEqual(self._scan(), [f"staged.txt：{self.DENIED}"])

    def test_staged_new_file_deleted_from_worktree_is_scanned_from_index(self):
        self._commit_file("baseline.txt", "乾淨內容")
        staged = self.repo / "staged-deleted.txt"
        staged.write_text(self.DENIED, encoding="utf-8")
        self._git("add", "staged-deleted.txt")
        staged.unlink()
        self.assertEqual(
            self._scan(), [f"staged-deleted.txt：{self.DENIED}"]
        )

    def test_deleted_worktree_file_falls_back_to_head(self):
        path = self._commit_file("deleted.txt", self.DENIED)
        path.unlink()
        self.assertEqual(self._scan(), [f"deleted.txt：{self.DENIED}"])

    def test_untracked_ignored_file_is_not_scanned(self):
        self._commit_file(".gitignore", "ignored.txt\n")
        (self.repo / "ignored.txt").write_text(self.DENIED, encoding="utf-8")
        self.assertEqual(self._scan(), [])

    def test_parent_symlink_outside_repo_is_not_followed(self):
        clean = self.repo / "clean-blob.txt"
        clean.write_text("乾淨 index 內容", encoding="utf-8")
        object_id = self._git("hash-object", "-w", "clean-blob.txt").stdout.strip()
        clean.unlink()
        self._git(
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{object_id},linked/secret.txt",
        )

        temp_root = Path(_ROOT) / ".tmp"
        with tempfile.TemporaryDirectory(
            prefix="pii-external-test-", dir=temp_root
        ) as outside_dir:
            outside = Path(outside_dir)
            (outside / "secret.txt").write_text(self.DENIED, encoding="utf-8")
            try:
                os.symlink(outside, self.repo / "linked", target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"目前環境不可建立目錄 symlink：{exc}")
            self.assertEqual(self._scan(), [])


def _git_at(root, *args):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), *args],
        capture_output=True,
    )
    if result.returncode:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"git {' '.join(args)} 失敗：{stderr}")
    return result.stdout


def _git(*args):
    return _git_at(_ROOT, *args)


def _is_within_repo(path, root):
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_worktree_blob(root, relative):
    """只讀取解析後每一層都留在 repo 內的工作樹 path。"""
    repo = Path(root).resolve(strict=True)
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return None

    path = repo.joinpath(*relative_path.parts)
    if not os.path.lexists(path):
        return None

    current = repo
    for part in relative_path.parts:
        current /= part
        try:
            # resolve 同時展開 symlink 與 Windows junction/reparse point。
            resolved = current.resolve(strict=True)
        except (FileNotFoundError, RuntimeError):
            return None
        if not _is_within_repo(resolved, repo):
            return None

    # git 對 final symlink 追蹤的是連結文字，不讀取其 target bytes。
    if path.is_symlink():
        return os.readlink(path).encode("utf-8")
    return path.read_bytes()


def _git_blob(root, object_spec):
    result = subprocess.run(
        ["git", "-C", os.fspath(root), "show", object_spec],
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def _tracked_blob(root, relative):
    """安全工作樹優先，其次 index，最後才回退 HEAD。"""
    worktree_blob = _safe_worktree_blob(root, relative)
    if worktree_blob is not None:
        return worktree_blob
    for object_spec in (f":{relative}", f"HEAD:{relative}"):
        blob = _git_blob(root, object_spec)
        if blob is not None:
            return blob
    return b""


def _text_hits(relative, blob, deny):
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return []
    return [f"{relative}：{name}" for name in deny if name in text]


def _scan_tracked_text(root, deny):
    """按安全工作樹、index、HEAD 順序掃描 git ls-files 所列文字檔。"""
    tracked = _git_at(root, "ls-files", "-z").split(b"\x00")
    hits = []
    for raw_relative in tracked:
        if not raw_relative:
            continue
        relative = raw_relative.decode("utf-8")
        if not relative.lower().endswith(_TEXT_EXT):
            continue
        hits.extend(_text_hits(relative, _tracked_blob(root, relative), deny))
    return hits


def _load_denylist():
    if not os.path.exists(_DENYLIST):
        return []
    names = []
    with open(_DENYLIST, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    return names


class TestNoPII(unittest.TestCase):
    def setUp(self):
        self.deny = _load_denylist()
        if not self.deny:
            self.skipTest(
                f"{os.path.relpath(_DENYLIST, _ROOT)} 不存在或無有效項目，"
                "跳過個資掃描"
            )

    def test_tracked_text_files_clean(self):
        """所有 git 追蹤的文字檔不得含 denylist 真名。"""
        hits = _scan_tracked_text(_ROOT, self.deny)
        self.assertEqual(
            hits, [],
            "git 追蹤檔含真實人名，替換後才能 push：\n  " + "\n  ".join(hits))

    def test_generated_shell_clean(self):
        """臨時產一份乾淨空殼（schema＋db_seed），其位元組不得含 denylist 真名。
        驗證 db_seed 的種子資料（佔位人員等）皆為虛構名，不會把真名帶進發版空殼。"""
        import sys, tempfile
        sys.path.insert(0, _ROOT)
        from tools import gen_shell_db
        temp_root = os.path.join(_ROOT, ".tmp")
        os.makedirs(temp_root, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            prefix="no-pii-shell-", suffix=".db", dir=temp_root
        )
        os.close(fd)
        os.remove(tmp)   # build 會自行建立
        try:
            gen_shell_db.build(tmp)
            with open(tmp, "rb") as f:
                blob = f.read()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        hits = [name for name in self.deny if name.encode("utf-8") in blob]
        self.assertEqual(
            hits, [],
            "產生的空殼含真實人名（db_seed 種子資料有真名），替換為虛構佔位名："
            "\n  " + "\n  ".join(hits))


if __name__ == "__main__":
    unittest.main()
