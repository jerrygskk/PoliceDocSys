"""刑案 ↔ 一般 類別互轉：純邏輯層（不依賴 Qt，可單測）。

設計凍結於 docs/handover_doc_convert.md。原則：
- 只做刑案 ↔ 一般（交辦單排除）；原號永久作廢，目標表配新號（Seq_DocId 每表獨立）
- 兩方向都會丟資料（欄位不對稱）；丟失欄寫進稽核 detail，可從操作紀錄查回
- 不進回收筒（決策 #5）
"""

import re

from lib.db_utils import (
    nextDocId, writeAudit, buildDetail, _DELETE_CLEAR_SQL,
)

# 來源類別 key → 轉換設定
_CONVERT = {
    "crim": {"src_table": "Document_Criminal", "dst_table": "Document_General",
             "dst_kind": "gen",  "src_cat": "刑案", "dst_cat": "一般"},
    "gen":  {"src_table": "Document_General",  "dst_table": "Document_Criminal",
             "dst_kind": "crim", "src_cat": "一般", "dst_cat": "刑案"},
}

# 丟失欄（不會帶入新單、寫進稽核）：src_kind → [(中文名, 欄位), ...]
_LOST_FIELDS = {
    "gen":  [("業務單位", "dept_id"), ("分類", "gen_cat_id")],
    "crim": [("案類", "case_type"), ("發文分類", "case_status"),
             ("受理日期", "occurrence_date"), ("受理人", "receiver_id"),
             ("報案人", "reporter_name")],
}


def convertKinds(src_kind):
    """回傳 (dst_kind, src_cat, dst_cat)；src_kind ∈ {'crim','gen'}。"""
    cfg = _CONVERT[src_kind]
    return cfg["dst_kind"], cfg["src_cat"], cfg["dst_cat"]


def mapGenToCrim(row):
    """一般列 dict → 刑案共通欄 dict（不含 doc_id 與補填欄）。"""
    return {
        "report_date":     row.get("report_date"),
        "sender_id":       row.get("sender_id"),
        "processor_id":    row.get("processor_id"),   # 陳報人 → 承辦人
        "subject_summary": row.get("subject"),        # 主旨欄名互換
        "is_reported":     row.get("is_reported"),
    }


def mapCrimToGen(row):
    """刑案列 dict → 一般共通欄 dict（不含 doc_id 與補填欄）。"""
    return {
        "report_date":  row.get("report_date"),
        "sender_id":    row.get("sender_id"),
        "processor_id": row.get("processor_id"),      # 承辦人 → 陳報人
        "subject":      row.get("subject_summary"),   # 主旨欄名互換
        "is_reported":  row.get("is_reported"),
    }


def lostFields(src_kind, row, name_resolver):
    """回傳丟失欄清單 [(欄位中文名, 顯示值), ...]（給補填視窗與稽核共用）。

    name_resolver(field, raw) -> 顯示字串：由呼叫端注入（查參照名／原樣回傳），
    讓純映射可離線測。值為空（顯示字串為空）就省略該項。
    """
    out = []
    for label, field in _LOST_FIELDS[src_kind]:
        disp = name_resolver(field, row.get(field))
        if disp:
            out.append((label, disp))
    return out


# 丟失欄 → (參照表, id 欄, 名稱欄)；不在表內者（日期／純文字）原樣回傳
_REF_LOOKUP = {
    "dept_id":     ("Ref_Departments",     "dept_id",      "dept_name"),
    "gen_cat_id":  ("Ref_General_Category", "gen_cat_id",  "gen_cat_name"),
    "case_type":   ("Ref_CaseTypes",       "case_type_id", "case_type_name"),
    "case_status": ("Ref_Case_Status",     "status_id",    "status_name"),
    "receiver_id": ("Ref_Personnel",       "staff_id",     "staff_name"),
}


def makeNameResolver(conn):
    """回傳 name_resolver(field, raw) -> 顯示名，供 lostFields／convertDoc 記顯示名。
    field 在 _REF_LOOKUP 內 → JOIN 參照表解析（查無回原 id）；否則原樣回傳。"""
    def resolve(field, raw):
        if not raw:
            return ""
        spec = _REF_LOOKUP.get(field)
        if spec is None:
            return str(raw)          # occurrence_date／reporter_name：原值即顯示
        table, id_col, name_col = spec
        try:
            r = conn.execute(
                f"SELECT {name_col} FROM {table} WHERE {id_col}=?", (raw,)
            ).fetchone()
            return r[0] if r and r[0] else str(raw)
        except Exception:
            return str(raw)
    return resolve


def renamePdfWithNewPk(old_name, new_pk):
    """歸檔檔名換 PK：切第一個 '-'／'－' 前的 PK 段換成 new_pk，其餘不動。
    防呆：old_name 無 '-' 時整檔名（去副檔名）視為 PK 換之。"""
    base = old_name or ""
    ext = ""
    if "." in base:
        base, dot, e = base.rpartition(".")
        ext = dot + e
    m = re.match(r"^\s*[^\-－]*([\-－].*)$", base)
    if m:                       # 有分隔符 → 保留第一個分隔符之後全部
        return f"{new_pk}{m.group(1)}{ext}"
    return f"{new_pk}{ext}"     # 無分隔符 → 整段視為 PK


def convertDoc(conn, *, src_kind, doc_id, fill_values, role, operator,
               is_electronic=None, name_resolver=None):
    """類別互轉的 transaction 核心（呼叫端負責 commit/rollback）。

    src_kind      'crim'（刑案→一般）／'gen'（一般→刑案）
    fill_values   補填欄 dict（目標表欄名 → 值），如刑案的 case_type/case_status…
    is_electronic None＝照搬來源；其餘（''／新檔名）＝呼叫端依 PDF 流程決定
    name_resolver 見 lostFields；供稽核 detail 記丟失欄顯示名（None＝不記丟失欄）

    回傳 (new_doc_id, src_row)；src_row 為原列快照 dict。
    """
    cfg = _CONVERT[src_kind]
    src_table, dst_table = cfg["src_table"], cfg["dst_table"]

    cur = conn.execute(f"SELECT * FROM {src_table} WHERE doc_id=?", (doc_id,))
    r = cur.fetchone()
    if r is None:
        raise ValueError(f"找不到來源公文：{doc_id}")
    src_row = dict(zip([d[0] for d in cur.description], r))

    new_id = nextDocId(conn, dst_table)

    mapped = mapGenToCrim(src_row) if src_kind == "gen" else mapCrimToGen(src_row)
    mapped.update(fill_values or {})
    mapped["is_electronic"] = (src_row.get("is_electronic") or "") \
        if is_electronic is None else is_electronic
    mapped["doc_id"] = new_id

    fields = list(mapped.keys())
    conn.execute(
        f"INSERT INTO {dst_table} ({','.join(fields)}) "
        f"VALUES ({','.join('?' * len(fields))})",
        [mapped[f] for f in fields])

    # 原列清空式 UPDATE（重用刪除的清空 SQL，勿重抄）
    conn.execute(_DELETE_CLEAR_SQL[src_table], (doc_id,))

    # 稽核一筆（不是刪除＋新增兩筆）
    subject = src_row.get("subject_summary") or src_row.get("subject") or ""
    content = f"{cfg['src_cat']}{doc_id}→{cfg['dst_cat']}{new_id} 主旨：{subject}"
    if name_resolver is not None:
        lost = lostFields(src_kind, src_row, name_resolver)
        if lost:
            content += "；未帶入欄位：" + "、".join(f"{k}={v}" for k, v in lost)
    writeAudit(conn, role=role, action="轉換", target_table=dst_table,
               target_id=new_id, operator=operator,
               detail=buildDetail(cfg["dst_cat"], "轉換", content))

    return new_id, src_row
