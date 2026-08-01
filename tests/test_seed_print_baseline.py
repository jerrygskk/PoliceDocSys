# -*- coding: utf-8 -*-
"""虛構列印基準資料庫產生工具的行為測試。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "seed_print_baseline.py"
GENERAL_DB = "dbfile.db"
MULTILINE_DB = "dbfile_multiline_title.db"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scalar(conn: sqlite3.Connection, sql: str, params=()):
    return conn.execute(sql, params).fetchone()[0]


def test_seed_tool_builds_complete_deterministic_fictional_databases(tmp_path):
    outputs = []
    for dirname in ("first", "second"):
        output_dir = tmp_path / dirname
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(output_dir)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "已建立虛構列印基準資料庫" in result.stdout
        assert sorted(path.name for path in output_dir.iterdir()) == [
            GENERAL_DB,
            MULTILINE_DB,
        ]
        outputs.append(output_dir)

    assert _sha256(outputs[0] / GENERAL_DB) == _sha256(outputs[1] / GENERAL_DB)
    assert _sha256(outputs[0] / MULTILINE_DB) == _sha256(
        outputs[1] / MULTILINE_DB
    )

    general_path = outputs[0] / GENERAL_DB
    multiline_path = outputs[0] / MULTILINE_DB
    with sqlite3.connect(general_path) as conn:
        schema_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        assert {
            "Document_Task",
            "Document_Criminal",
            "Document_General",
            "Document_Reward",
            "Document_Ticket",
            "View_Task_Full",
            "View_Criminal_Full",
            "View_General_Full",
            "Document_Ticket_Full",
        } <= schema_names
        assert _scalar(
            conn,
            "SELECT value FROM App_Settings WHERE key='report_mode_ticket'",
        ) == "0"

        assert conn.execute(
            "SELECT staff_id,staff_name FROM Ref_Personnel ORDER BY sort_order"
        ).fetchall() == [
            ("P01", "測試甲"),
            ("P02", "測試乙"),
            ("P03", "測試丙"),
            ("P04", "測試丁"),
            ("P05", "測試戊"),
            ("P06", "測試己"),
        ]

        expected_counts = {
            "Document_Task": {
                "2026-05-11": 16,
                "2026-02-23": 16,
                "2026-06-22": 4,
                "2026-08-10": 4,
            },
            "Document_Criminal": {
                "2026-05-11": 26,
                "2026-02-23": 22,
                "2026-06-22": 31,
                "2026-08-10": 3,
            },
            "Document_General": {
                "2026-05-11": 16,
                "2026-02-23": 39,
                "2026-06-22": 14,
                "2026-08-10": 2,
            },
            "Document_Reward": {
                "2026-05-11": 5,
                "2026-08-10": 2,
            },
            "Document_Ticket": {
                "2026-07-26": 180,
                "2026-07-25": 10,
                "2026-08-11": 27,
            },
        }
        date_columns = {
            "Document_Task": "dispatch_date",
            "Document_Criminal": "report_date",
            "Document_General": "report_date",
            "Document_Reward": "register_date",
            "Document_Ticket": "register_date",
        }
        for table, by_date in expected_counts.items():
            assert _scalar(conn, f"SELECT count(*) FROM {table}") == sum(
                by_date.values()
            )
            for date_text, expected in by_date.items():
                assert _scalar(
                    conn,
                    f"SELECT count(*) FROM {table} WHERE {date_columns[table]}=?",
                    (date_text,),
                ) == expected

        for table, date_column in date_columns.items():
            assert _scalar(
                conn,
                f"SELECT count(*) FROM {table} WHERE {date_column}='2026-01-01'",
            ) == 0

        assert _scalar(
            conn,
            "SELECT count(*) FROM Document_Criminal "
            "WHERE report_date='2026-05-11' AND case_status='CS01'",
        ) == 13
        for table, column in (
            ("Document_Task", "subject"),
            ("Document_Criminal", "subject_summary"),
            ("Document_General", "subject"),
            ("Document_Reward", "reason"),
        ):
            assert _scalar(
                conn,
                f"SELECT max(length({column})) FROM {table} "
                "WHERE " + date_columns[table] + "='2026-08-10'",
            ) >= 100
        assert _scalar(
            conn,
            "SELECT max(length(case_type_name)) FROM Ref_CaseTypes",
        ) >= 30
        assert _scalar(
            conn,
            "SELECT count(*) FROM Document_Ticket "
            "WHERE register_date='2026-08-11' AND length(ticket_no)=28",
        ) >= 1
        assert _scalar(
            conn,
            "SELECT count(*) FROM Document_Ticket "
            "WHERE register_date='2026-08-11' AND issuer_id='P01'",
        ) >= 20

    with sqlite3.connect(multiline_path) as conn:
        titles = dict(
            conn.execute(
                "SELECT key,value FROM App_Settings "
                "WHERE key IN ('print_title_task','print_title_ticket')"
            )
        )
        assert "\n" in titles["print_title_task"]
        assert "\n" in titles["print_title_ticket"]
        assert _scalar(
            conn,
            "SELECT count(*) FROM Document_Task WHERE dispatch_date='2026-08-10'",
        ) == 4
        assert _scalar(
            conn,
            "SELECT count(*) FROM Document_Ticket WHERE register_date='2026-08-11'",
        ) == 27
