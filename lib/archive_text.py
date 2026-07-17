"""歸檔比對用的純文字/檔名工具（無 Qt、無狀態）。

從 tabs/tab_archive.py 抽出，便於單獨單元測試。
名稱保留底線前綴以維持呼叫端不變（顯式 import 不受 `_` 影響）。
"""
import os
import re


def _trimName(name):
    """承辦人去後綴：匿名-01 / 匿名-19.06 → 匿名 / 匿名"""
    if not name:
        return ""
    return re.split(r"[-－]", str(name))[0].strip()


def _tokenize(text):
    """斷詞：依分隔符切；再從每個片段抽出其中的中文連續段做 2 字滑動片段。
    （檔名常見日期與主旨黏連，如 1150101匿名竊盜案，需抽出中文段才比得到。）"""
    toks = set()
    for x in re.split(r"[\s_\-－.,，、（）()]+", str(text)):
        x = x.strip()
        if len(x) >= 2:
            toks.add(x)
        # 抽出片段內所有中文連續段（即使與數字/英文黏連）
        for seg in re.findall(r"[\u4e00-\u9fff]+", x):
            if len(seg) >= 2:
                toks.add(seg)
            if len(seg) >= 3:
                for i in range(len(seg) - 1):
                    toks.add(seg[i:i + 2])
    return toks


def _parseDate(filename):
    r"""從舊檔名拆出日期片段，拆不到回空字串。
    以民國年為主（7 碼緊湊：1150612 = 115年6月12日），抓不到再試西元 8 碼。

    ⚠️ 正規檔名為「PK-日期-主旨-承辦」，開頭 PK 也是 1xx（如 103-1150120-…）。
    日期 token 必須前後不接數字（`(?<!\d)…(?!\d)`），否則 PK「103」會被當成
    民國年、咬住後方數字湊成不合理日期而整串解析失敗（README 踩雷表已記載）。
    實務檔名日期中間不含分隔符，故用緊湊式即可，不容忍 115-06-12。
    """
    base = os.path.splitext(filename)[0]
    # 民國年：前後不接數字的 1xx + 2碼月 + 2碼日，並做月/日合理性檢查
    for pat in (r"(?<!\d)(1\d{2})(\d{2})(\d{2})(?!\d)",
                r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)"):
        for m in re.finditer(pat, base):
            mo, d = int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return ""


def _sanitize(text):
    """檔名安全化：移除 Windows 不允許的字元。"""
    return re.sub(r'[\\/:*?"<>|]', "", str(text or "")).strip()


def _pkOf(filepath):
    """取檔名最前段（第一個 - / － 之前）為 PK；正規檔名格式為 PK-日期-…。"""
    base = os.path.splitext(os.path.basename(filepath))[0]
    m = re.match(r"^\s*([^\-－]+)", base)
    return m.group(1).strip() if m else ""


# ── 主旨／承辦人解析（需人名字典；呼叫端餵 DB 載入的 name_dict）──────────
# 承辦人區界定一律「對得到人名字典才算承辦人」：從尾端往前，純數字(日期/PK)即停，
# 對到字典(含去姓2字/別名)收為承辦人，對不到(案由/被害人/報案人)即停。
# 不再用「≤3字一律當人名」，避免把「竊盜案」等案由詞、括號內報案人誤收成承辦人。

# 車牌／案號連字號（MQM-1763、P77-965、822-NHS、9362-F6…）：兩側英數，整段至少含一字母
# 才視為車牌（純數字-數字如日期/PK 不遮罩）。
_PLATE_DASH_RE = re.compile(r"[A-Za-z0-9]{2,5}[-－][A-Za-z0-9]{2,6}")
# 開頭（PK-）日期：遮罩車牌前先抓出保護，避免日期尾數字與車牌頭被連在一起。
_HEAD_DATE_RE = re.compile(
    r"\s*(?:\d+[-－])*(?:1\d{2}|20\d{2})[-.\/]?\d{1,2}[-.\/]?\d{1,2}")
_PLATE_SENT = "\x01"   # 遮罩用哨兵，組完主旨後還原成 -
_LEAD_DATE_RE = re.compile(r"^\s*(?:1\d{2}|20\d{2})[-.\/]?\d{1,2}[-.\/]?\d{1,2}")


def _maskPlateDash(text):
    """把車牌型連字號的 - 暫換成哨兵，避免被當主旨/人名分隔符切散。"""
    def repl(m):
        s = m.group(0)
        if re.search(r"[A-Za-z]", s):   # 含字母才視為車牌/案號
            return s.replace("-", _PLATE_SENT).replace("－", _PLATE_SENT)
        return s
    return _PLATE_DASH_RE.sub(repl, text)


def _stripStaffParen(subj, name_dict):
    """主旨尾端括號內若全是承辦/協辦（皆能對到人名字典）則整組去掉；
    對不到（被害人、報案人、關係人等不在名單）則保留。"""
    m = re.search(r"[（(]([^（）()]*)[）)]\s*$", subj)
    if not m:
        return subj
    parts = [p for p in re.split(r"[、,，/／\s]+", m.group(1)) if p.strip()]
    if parts and all(p in name_dict for p in parts):
        return subj[:m.start()].strip()
    return subj


def _resolveNames(old_path, name_dict):
    """解析舊檔名的人名區並補全名。
    從尾端往前收：純數字(日期/PK)即停；能對到人名字典(含去姓2字/別名)才收為承辦人，
    對不到(案由/被害人/報案人)即停。對到的補全名/別名，回傳去重後的全名清單。"""
    base = os.path.splitext(os.path.basename(old_path))[0]
    pieces = [p for p in re.split(r"[-－.、，,（）()／/_\s·．]+", base) if p.strip()]
    picked = []
    for p in reversed(pieces):
        if re.fullmatch(r"\d+", p):          # 純數字 → 離開人名區
            break
        if p in name_dict:                    # 對到人名字典 → 承辦人
            picked.insert(0, p)
        else:                                 # 對不到(案由/被害人/報案人) → 停
            break
    out, seen = [], set()
    for p in picked:
        name = name_dict.get(p, p)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _parseSubject(old_path, name_dict):
    """從舊檔名拆主旨。支援兩種格式：
    (1) 已格式化「PK-日期-主旨-承辦[-承辦…]」：以 - 分段，去開頭純數字段；
        從尾端用人名字典迴圈剝除承辦人段（尾段可含頓號多人），碰到對不到的(主旨)停。
    (2) 實務候選檔「日期+主旨(報案人)」(無 -)：去開頭日期，再從尾端用字典剝承辦人。
    報案人非承辦人，不會被當成人名剝掉。拆不到回空字串（呼叫端退用 DB 主旨）。"""
    base = os.path.splitext(os.path.basename(old_path))[0]
    # 遮罩車牌連字號前先保護開頭（PK-）日期，避免日期尾數字與車牌頭被連起來。
    m = _HEAD_DATE_RE.match(base)
    head = base[:m.end()] if m else ""
    base = head + _maskPlateDash(base[m.end():] if m else base)
    unmask = lambda s: s.replace(_PLATE_SENT, "-")

    # 格式 (1)：含 - 分隔
    if re.search(r"[-－]", base):
        segs = [s.strip() for s in re.split(r"[-－]", base) if s.strip()]
        if not segs:
            return ""
        i = 0
        while i < len(segs) and re.fullmatch(r"\d+", segs[i]):
            i += 1
        j = len(segs)
        # 從尾端用字典迴圈剝承辦人段：尾段(可含頓號多人，如「王測乙、王測甲」)
        # 所有人名都對得到字典 → 整段是承辦人區、移除；碰到對不到的(主旨段)停。
        # 至少保留一段主旨(j-1 > i)，避免把主旨整段砍空。
        while j - 1 > i:
            toks = [t for t in re.split(r"[、,，]+", segs[j - 1]) if t.strip()]
            if toks and all(t in name_dict for t in toks):
                j -= 1
            else:
                break
        mid = segs[i:j]
        # 日期可能與主旨黏在同一段（如「1150617陳若蘭詐欺」），剝掉首段開頭日期。
        if mid:
            mid[0] = _LEAD_DATE_RE.sub("", mid[0]).strip()
            mid = [x for x in mid if x]
        return _stripStaffParen(unmask("、".join(mid)), name_dict) if mid else ""

    # 格式 (2)：無 - → 去開頭日期 + 從尾端用字典剝承辦人
    s = _LEAD_DATE_RE.sub("", base)
    if s == base:                      # 開頭非日期格式 → 至少去掉開頭連續數字
        s = re.sub(r"^\s*\d+", "", base)
    pieces = [p for p in re.split(r"[-－.、，,（）()／/_\s·．]+", s) if p.strip()]
    while pieces:
        p = pieces[-1]
        if re.fullmatch(r"\d+", p):
            break
        if p in name_dict:             # 對到字典才當承辦人剝除
            pieces.pop()
        else:
            break
    return _stripStaffParen(unmask("".join(pieces)), name_dict)
