"""列印畫布介面：把簽收表的繪圖呼叫與繪圖引擎隔開。

存在目的是讓 `tabs/tab_print.py` 的版面程式碼不直接綁死任何一種繪圖引擎。
**產品預設（階段 3 起）走 `QtCanvas`**——本檔不 import matplotlib，
`lib/` 底下任何檔案都不得 import matplotlib／numpy／PIL（見
`tools/check_no_matplotlib.py`）。matplotlib 的實作 `MatplotlibCanvas`
已移到 `tools/mpl_canvas.py`，繼續當 `tools/print_baseline.py`／
`tools/render_diff.py` 等比對工具的參考引擎用，不在產品路徑上。

座標一律 normalized 0~1，**y 軸向上**（沿用 matplotlib 慣例，
`tabs/tab_print.py` 的版面常數才不用改）。

⚠️ `linespacing`／`multialignment` 預設 `None`＝**不覆寫引擎自己的預設**；
只有原本就指定這兩個值的呼叫端（`_draw_page()` 的資料列文字）才明確傳入。
改成無條件填值的話，單行文字看不出差異，但多行文字的行距與對齊會與原版
不同——換引擎時才爆，屬於極難追查的雷。

⚠️ `QtCanvas`（階段 2 新增，階段 3 起成為產品唯一引擎）用 QPainter 實作
同一組介面。
"""

from collections import namedtuple


class Canvas:
    """一頁 A4 的繪圖介面。座標一律 normalized 0~1，**y 軸向上**
    （沿用 matplotlib 慣例，原始碼的版面常數才不用動）。"""

    def text(self, x, y, s, *, size, bold=False, ha='left', va='center',
             color='#111111', linespacing=None, multialignment=None,
             clip_rect=None):
        """clip_rect=(x0, y0, x1, y1) normalized，None 表不裁切。
        linespacing／multialignment 為 None 表不覆寫 matplotlib 預設。"""
        raise NotImplementedError

    def rect(self, x, y, w, h, *, facecolor=None, edgecolor=None,
             linewidth=0, zorder=1):
        """facecolor=None 表不填色；edgecolor=None 表不描邊。"""
        raise NotImplementedError

    def line(self, x0, y0, x1, y1, *, color, linewidth, zorder=2):
        raise NotImplementedError


# ── Qt 字型檔載入（QtCanvas 與 tab_print._qt_text_width_pt 共用）───────
# A4 直向頁面英吋尺寸。須與 tabs/tab_print.py 的 A4_W／A4_H 完全一致
# （normalized 座標換算 pt／device px 都靠它）；兩處各自定義一份是為了
# 避免本檔反向 import tab_print 造成循環（見檔頭說明）。
A4_W_IN = 8.27
A4_H_IN = 11.69

_APPLICATION_FONT_FAMILY_CACHE = {}


def _load_font_family(path):
    """把字型檔載入 QFontDatabase，回傳**第一個** family 名稱。

    ⚠️ 不可用家族名字串硬寫：msjh.ttc 回傳
    `['Microsoft JhengHei', '微軟正黑體', 'Microsoft JhengHei UI']`，
    第一個才是正確的正體家族，其餘是 UI／別名變體，度量會不同
    （改造前實測結論）。同一路徑只載入一次並快取。
    """
    family = _APPLICATION_FONT_FAMILY_CACHE.get(path)
    if family is not None:
        return family
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    if QGuiApplication.instance() is None:
        raise RuntimeError(
            '_load_font_family() 需先建立 QGuiApplication 才能使用 '
            'QFontDatabase（未建立時整個 process 會直接 segfault、無 '
            'traceback）；請先建立 QGuiApplication 實例再呼叫本函式。')
    font_id = QFontDatabase.addApplicationFont(path)
    if font_id == -1:
        raise RuntimeError(f'QFontDatabase 無法載入字型檔：{path}')
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError(f'字型檔沒有回傳任何 family：{path}')
    family = families[0]
    _APPLICATION_FONT_FAMILY_CACHE[path] = family
    return family


# matplotlib `Text._get_layout()` 拿來當每行高度／descent 下限的參考
# 字串，字面就是這兩個字元（含一個 ascender、一個 descender），見
# `QtCanvas.text()` 垂直置中一段的說明。
_LP_REF = 'lp'


class QtCanvas(Canvas):
    """用 QPainter 實作 Canvas。`painter` 由呼叫端建好並傳入（QImage／
    QPdfWriter／QPrinter 三種 device 共用同一份繪圖碼），本類別只管畫，
    不管 painter 畫在哪個 device 上、也不重新量測換行／字級。

    ⚠️ **zorder 沒有作用**：Qt 沒有 zorder 概念，繪製結果依呼叫順序疊放。
    呼叫端目前的呼叫順序＝階段 1 保證過的正確疊放順序，故本類別直接照收到
    的順序畫，不做任何排序或延後繪製。

    座標換算：`width_px`／`height_px` 是這次要畫的 device 的像素尺寸，
    用來把 normalized 座標換算成 device px；device 的等效 dpi 由
    `width_px / A4_W_IN` 反推（假設呼叫端已依 A4 直向比例算好像素尺寸）。
    字級（pt）與線寬（pt）也依同一個 dpi 換算成 device px，所以同一份
    op 在不同解析度的 painter 上畫出來仍是同一張圖的等比例縮放。

    垂直置中對齊 matplotlib `Text._get_layout()` 的實際演算法（見
    matplotlib/text.py）：不是單純對墨跡框置中，也不是 Qt 的
    `AlignVCenter`／line box——而是拿參考字串 `"lp"`（同字型量出來的
    ascender／descender）當每行高度／descent 的下限（`h=max(該行h,
    lp的h)`、`d=max(該行d, lp的d)`）。STAGE2-FIX-BRIEF §2-3：純墨跡框
    置中對純 CJK 文字（沒有下伸部）會比 matplotlib 偏上約 1.7pt（列高
    43.8pt 的 4%）——本案簽收單是對外紙本、版面不能走鐘，決策是忠實對齊
    matplotlib 現況，不採用「客觀上更正確」的墨跡置中。做法：`text()`
    裡用 `tightBoundingRect("lp")` 與該行文字自己的 `tightBoundingRect()`
    取聯集模擬同一個效果。
    """

    def __init__(self, painter, width_px, height_px, font_paths):
        self.painter = painter
        self.width_px = width_px
        self.height_px = height_px
        reg_path, bold_path = font_paths
        self._reg_family = _load_font_family(reg_path)
        # 只為了把粗體字重的字型面註冊進 QFontDatabase（同一 family 底下
        # 才會多出一個可選字重）；回傳值不另外快取——本機 msjh.ttc／
        # msjhbd.ttc 回傳的 family 名完全相同，留一份「形同虛設的 bold
        # family」只會誤導後續維護者以為靠 family 名切字重。字重一律靠
        # `_font()` 明確呼叫 `setBold()`，不依賴 family 名是否有分開。
        _load_font_family(bold_path)
        self._dpi = width_px / A4_W_IN

        from PySide6.QtGui import QPainter as _QPainter
        painter.setRenderHint(_QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(_QPainter.RenderHint.TextAntialiasing, True)

    # ── 座標／單位換算 ──────────────────────────────
    def _to_device(self, x, y):
        """normalized (0~1, y 向上) → device px (原點左上, y 向下)。
        不用 painter.scale(w, -h) 做全域翻轉（那會讓文字上下顛倒），
        逐點換算。"""
        return x * self.width_px, (1 - y) * self.height_px

    def _pt_to_device(self, pt):
        return pt * self._dpi / 72.0

    # `text()` 內部用來量測／排版的字型以這個倍率超取樣（見 `text()` 內的
    # 說明）；`painter.scale()` 縮回來後，最終畫在頁面上的字級不變。
    _TEXT_SUPERSAMPLE = 8

    def _font(self, size, bold, supersample=1):
        from PySide6.QtGui import QFont
        f = QFont(self._reg_family)
        f.setBold(bool(bold))
        f.setPixelSize(max(1, round(self._pt_to_device(size) * supersample)))
        # hinting 刻意不設（維持 Qt 預設 PreferDefaultHinting）：STAGE2-FIX-
        # BRIEF §2-3 曾把它設成 PreferVerticalHinting，理由是「能把驗收數字
        # 從 0.57pt 壓到 0.48pt」——但那是拿驗收數字反推產品的字型渲染設定，
        # 順序反了。STAGE2-FIX2-BRIEF §3 決定改回預設，但 300dpi 實測顯示
        # `setPixelSize()` 只吃整數 px 這件事本身，會讓不同字級的取整誤差
        # 經 hinting 對齊像素格線放大成 1~2.6px 的垂直置中偏移（`text()`
        # 改用超取樣後這塊誤差大幅收斂，見 `text()` 內的完整說明與交付
        # 報告的實測數據）——問題不是「該選哪個 hinting」，是量測／排版的
        # 字級太小，取整（`setPixelSize` 只收 int）與 hinting 對齊格線的
        # 影響被相對放大；供 `text()` 呼叫，其餘呼叫端（若有）維持
        # `supersample=1` 不受影響。
        return f

    def rect(self, x, y, w, h, *, facecolor=None, edgecolor=None,
             linewidth=0, zorder=1):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPen
        x0, y0 = self._to_device(x, y + h)
        x1, y1 = self._to_device(x + w, y)
        r = QRectF(x0, y0, x1 - x0, y1 - y0)
        if facecolor is not None:
            self.painter.fillRect(r, QColor(facecolor))
        if edgecolor is not None and linewidth:
            old_pen = self.painter.pen()
            pen = QPen(QColor(edgecolor))
            pen.setWidthF(self._pt_to_device(linewidth))
            self.painter.setPen(pen)
            self.painter.drawRect(r)
            self.painter.setPen(old_pen)

    def line(self, x0, y0, x1, y1, *, color, linewidth, zorder=2):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QPen
        dx0, dy0 = self._to_device(x0, y0)
        dx1, dy1 = self._to_device(x1, y1)
        old_pen = self.painter.pen()
        pen = QPen(QColor(color))
        pen.setWidthF(self._pt_to_device(linewidth))
        self.painter.setPen(pen)
        self.painter.drawLine(QPointF(dx0, dy0), QPointF(dx1, dy1))
        self.painter.setPen(old_pen)

    def text(self, x, y, s, *, size, bold=False, ha='left', va='center',
             color='#111111', linespacing=None, multialignment=None,
             clip_rect=None):
        if not s:
            return
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QFontMetricsF

        # ── 超取樣（STAGE2-FIX2-BRIEF §2／§3 交付報告根因說明）─────────
        # `QFont.setPixelSize()` 只收整數 px；在常見字級（8~14pt）×
        # 150~300dpi 下，換算後的 device px 常常不是整數，取整造成的字級
        # 誤差經 Qt 的 hinting（不論哪種 hinting 模式，含完全關閉）對齊像素
        # 格線後，會被放大成每格垂直置中最多 ~2.6px 的偏移——實測改成
        # `PreferNoHinting` 或 `PreferVerticalHinting` 結果幾乎不變，證明
        # 這不是 hinting 選擇的問題，是取整後的字級本身就與 mpl（FreeType，
        # 全程浮點精度）不一致。
        # 修法：字型放大 `_TEXT_SUPERSAMPLE` 倍量測與繪製，`painter.scale()`
        # 縮回來，讓「setPixelSize 只能取整數」造成的相對誤差縮小到
        # 1/_TEXT_SUPERSAMPLE，最終頁面上的字級（縮放後）不變。實測（見
        # 交付報告）把最壞情形從 2.6px 壓到 ~1.2px，且對 hinting 模式不再
        # 敏感（確認殘餘量是 Qt／FreeType 兩種字型引擎本身對同一字型檔的
        # 度量微小差異，非取整或 hinting 造成，無法再靠渲染設定消除）。
        ss = self._TEXT_SUPERSAMPLE
        font = self._font(size, bold, supersample=ss)
        metrics = QFontMetricsF(font)
        lines = s.split('\n')
        align = multialignment or ha

        old_font = self.painter.font()
        old_pen = self.painter.pen()
        self.painter.setFont(font)
        self.painter.setPen(QColor(color))

        # 縮放與裁切都要在同一個 save／restore 區塊內、且 clip 要用「超取樣
        # 後」的座標設（乘 ss）：`setClipRect()` 是在呼叫當下的座標系統
        # （已經 scale 過）解讀，兩者不同座標系統混用會裁到錯的範圍。
        self.painter.save()
        self.painter.scale(1.0 / ss, 1.0 / ss)

        if clip_rect is not None:
            cx0, cy0 = self._to_device(clip_rect[0], clip_rect[3])
            cx1, cy1 = self._to_device(clip_rect[2], clip_rect[1])
            self.painter.setClipRect(QRectF(cx0 * ss, cy0 * ss, (cx1 - cx0) * ss, (cy1 - cy0) * ss))

        # 多行行距：linespacing 有指定就依它換算（乘上字級的 device px），
        # 否則用 Qt 字型自己的預設行距。以下所有
        # 座標都在「超取樣」空間（× ss）算，畫的時候用 painter.scale(1/ss)
        # 縮回真正的 device px。
        line_step = (
            linespacing * self._pt_to_device(size) * ss if linespacing is not None
            else metrics.lineSpacing())
        line_widths = [metrics.horizontalAdvance(ln) for ln in lines]
        block_w = max(line_widths) if line_widths else 0.0

        anchor_x, anchor_y = self._to_device(x, y)
        anchor_x, anchor_y = anchor_x * ss, anchor_y * ss
        if ha == 'left':
            block_x0 = anchor_x
        elif ha == 'right':
            block_x0 = anchor_x - block_w
        else:
            block_x0 = anchor_x - block_w / 2

        # 垂直置中：對齊 matplotlib va='center' 的實際演算法（見本類別
        # docstring／STAGE2-FIX-BRIEF §2-3）。matplotlib `Text._get_layout()`
        # 不是單純對「墨跡框」或「字型 ascent/descent」置中，而是拿參考字串
        # `"lp"`（同字型量出來的 l 的 ascender、p 的 descender）當每行的
        # 「最小」高度／descent：`h=max(該行墨跡h, lp的h)`、
        # `d=max(該行墨跡d, lp的d)`。純 CJK 沒有下伸部，墨跡本身的 d 遠小於
        # `lp` 的 d，於是被 `lp` 的 descent 頂高——這正是原本改用純墨跡框
        # 置中會偏上 1.7pt 的原因。用 `tightBoundingRect("lp")` 與該行文字
        # 自己的 `tightBoundingRect()` 取聯集（top 取最小、bottom 取最大）
        # 逼近同一個效果；實測與 mpl 的差距可壓到 0.1pt 內（見
        # STAGE2-FIX-BRIEF 交付報告的實測數字）。
        lp_box = metrics.tightBoundingRect(_LP_REF)
        first_box = metrics.tightBoundingRect(lines[0])
        last_box = metrics.tightBoundingRect(lines[-1])
        block_top = min(first_box.top(), lp_box.top())
        block_bottom = (len(lines) - 1) * line_step + max(last_box.bottom(), lp_box.bottom())
        block_h = block_bottom - block_top
        if va == 'top':
            first_baseline = anchor_y - block_top
        elif va == 'bottom':
            first_baseline = anchor_y - block_bottom
        elif va == 'center':
            first_baseline = anchor_y - block_top - block_h / 2
        else:
            first_baseline = anchor_y

        for i, (ln, lw) in enumerate(zip(lines, line_widths)):
            if align == 'left':
                lx = block_x0
            elif align == 'right':
                lx = block_x0 + block_w - lw
            else:
                lx = block_x0 + (block_w - lw) / 2
            self.painter.drawText(QPointF(lx, first_baseline + i * line_step), ln)

        self.painter.restore()
        self.painter.setFont(old_font)
        self.painter.setPen(old_pen)


TextOp = namedtuple('TextOp', [
    'x', 'y', 's', 'size', 'bold', 'ha', 'va', 'color',
    'linespacing', 'multialignment', 'clip_rect'])
RectOp = namedtuple('RectOp', [
    'x', 'y', 'w', 'h', 'facecolor', 'edgecolor', 'linewidth', 'zorder'])
LineOp = namedtuple('LineOp', [
    'x0', 'y0', 'x1', 'y1', 'color', 'linewidth', 'zorder'])


class RecordingCanvas(Canvas):
    """把每次呼叫記成一筆 op（`ops` 屬性可取出）。`inner` 不為 None 時
    同時轉發給內層 canvas，讓「畫圖」與「錄製」一次完成。"""

    def __init__(self, inner=None):
        self.inner = inner
        self.ops = []

    def text(self, x, y, s, *, size, bold=False, ha='left', va='center',
             color='#111111', linespacing=None, multialignment=None,
             clip_rect=None):
        self.ops.append(TextOp(
            x, y, s, size, bold, ha, va, color,
            linespacing, multialignment, clip_rect))
        if self.inner is not None:
            return self.inner.text(
                x, y, s, size=size, bold=bold, ha=ha, va=va, color=color,
                linespacing=linespacing, multialignment=multialignment,
                clip_rect=clip_rect)

    def rect(self, x, y, w, h, *, facecolor=None, edgecolor=None,
             linewidth=0, zorder=1):
        self.ops.append(RectOp(
            x, y, w, h, facecolor, edgecolor, linewidth, zorder))
        if self.inner is not None:
            return self.inner.rect(
                x, y, w, h, facecolor=facecolor, edgecolor=edgecolor,
                linewidth=linewidth, zorder=zorder)

    def line(self, x0, y0, x1, y1, *, color, linewidth, zorder=2):
        self.ops.append(LineOp(x0, y0, x1, y1, color, linewidth, zorder))
        if self.inner is not None:
            return self.inner.line(
                x0, y0, x1, y1, color=color, linewidth=linewidth,
                zorder=zorder)
