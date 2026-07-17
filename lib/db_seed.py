# -*- coding: utf-8 -*-
"""乾淨空殼的「種子資料」唯一來源：參照資料、預設密碼、Seq 歸零。

只在「建全新空庫」時套用（由 tools/gen_shell_db.py 呼叫）；
刻意「不」掛進啟動 ensureSchema，避免對既有庫重塞參照資料。
全程 INSERT OR IGNORE，對已有資料的庫為 no-op。

預設密碼（admin / 0000 的 SHA-256）暫塞於此；威脅模型下可接受，
日後若改首次啟動強制設定再移除（見 docs/handover 待議）。
簽收表四個 key 以空值播種＝維持「未設定」紅字提醒（printTitlesUnset 視空為未設定）。
"""

# (staff_id, staff_name, is_active, sort_order, alias)
PERSONNEL = (
    ('P01', '王小明', 1, 1, '所長,王佐'),
)

# (dept_id, dept_name, is_active, sort_order)
DEPARTMENTS = (
    ('D01', '交通組', 1, 1),
    ('D02', '偵查隊', 1, 2),
    ('D03', '防治組', 1, 3),
    ('D04', '行政組', 1, 4),
    ('D05', '督察組', 1, 5),
    ('D06', '人事室', 1, 6),
    ('D07', '保民組', 1, 7),
    ('D08', '保防組', 1, 8),
    ('D09', '秘書室', 1, 9),
    ('D10', '會計室', 1, 10),
    ('D11', '勤指中心', 1, 11),
)

# (case_type_id, case_type_name, is_active, sort_order)
CASE_TYPES = (
    ('CT01', '通緝', 1, 1),
    ('CT02', '毒品危害防制條例', 1, 2),
    ('CT03', '185-3公共危險(酒)', 1, 3),
    ('CT04', '185-3公共危險(毒)', 1, 4),
    ('CT05', '320竊盜', 1, 5),
    ('CT06', '321加重竊盜', 1, 6),
    ('CT07', '339詐欺', 1, 7),
    ('CT08', '失聯移工', 1, 8),
    ('CT09', '185-4肇事逃逸', 1, 9),
    ('CT10', '277傷害', 1, 10),
    ('CT11', '284過失傷害', 1, 11),
    ('CT12', '302妨害自由(私行拘禁)', 1, 12),
    ('CT13', '304強制罪', 1, 13),
    ('CT14', '306侵入住宅', 1, 14),
    ('CT15', '309-314妨害名譽及信用(公然侮辱、誹謗)', 1, 15),
    ('CT16', '335侵占', 1, 16),
    ('CT17', '354毀損', 1, 17),
    ('CT18', '358妨害電腦使用', 1, 18),
    ('CT19', '汽機車遺失/侵占/失竊', 1, 19),
    ('CT20', '汽機車車牌遺失/侵占/失竊', 1, 20),
    ('CT21', '其他汽機車案類', 1, 21),
    ('CT22', '社會秩序維護法', 1, 22),
    ('CT23', '家庭暴力防治法', 1, 23),
    ('CT24', '個人資料保護法', 1, 24),
    ('CT25', '跟蹤騷擾防治法', 1, 25),
    ('CT26', '性騷擾防治法', 1, 26),
    ('CT27', '★★刑案類找不到法條(暫選)', 1, 27),
)

# (status_id, status_name)
CASE_STATUS = (
    ('CS01', '現行'),
    ('CS02', '到案'),
    ('CS03', '未到'),
)

# (gen_cat_id, gen_cat_name)
GENERAL_CATEGORY = (
    ('GC01', '業務'),
    ('GC02', '相驗'),
    ('GC03', '其他'),
)

# (table_name, last_id)
SEQ_DOCID = (
    ('Document_Criminal', 0),
    ('Document_General', 0),
    ('Document_Reward', 0),
    ('Document_Task', 0),
)

# (key, value)
APP_SETTINGS = (
    ('admin_password_hash', '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'),
    ('archive_password_hash', '9af15b336e6a9619928537df30b2e6a2376569fcf9d7e773eccede65606529a0'),
    ('archive_root', ''),
    ('archive_subdir_crim', ''),
    ('archive_subdir_gen', ''),
    ('print_title_task', ''),
    ('print_title_crim', ''),
    ('print_title_gen', ''),
    ('print_title_reward', ''),
    ('print_note_current', ''),
)


def seedFreshDb(conn):
    """對全新空庫播入種子（INSERT OR IGNORE，冪等）。呼叫端負責 commit。"""
    conn.executemany(
        "INSERT OR IGNORE INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order,alias) VALUES(?,?,?,?,?)",
        PERSONNEL)
    conn.executemany(
        "INSERT OR IGNORE INTO Ref_Departments(dept_id,dept_name,is_active,sort_order) VALUES(?,?,?,?)",
        DEPARTMENTS)
    conn.executemany(
        "INSERT OR IGNORE INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order) VALUES(?,?,?,?)",
        CASE_TYPES)
    conn.executemany(
        "INSERT OR IGNORE INTO Ref_Case_Status(status_id,status_name) VALUES(?,?)",
        CASE_STATUS)
    conn.executemany(
        "INSERT OR IGNORE INTO Ref_General_Category(gen_cat_id,gen_cat_name) VALUES(?,?)",
        GENERAL_CATEGORY)
    conn.executemany(
        "INSERT OR IGNORE INTO Seq_DocId(table_name,last_id) VALUES(?,?)",
        SEQ_DOCID)
    conn.executemany(
        "INSERT OR IGNORE INTO App_Settings(key,value) VALUES(?,?)",
        APP_SETTINGS)
