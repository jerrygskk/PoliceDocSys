# -*- coding: utf-8 -*-
"""matplotlib 版繪圖引擎：階段 3 從 `lib/print_canvas.py` 搬出來的
`MatplotlibCanvas`，連同它的字型度量器 `mpl_text_width_pt()`。

**只給 `tools/` 底下的比對／基準工具用**（`tools/print_baseline.py`／
`tools/render_diff.py`／`tools/engine_diff.py`／`tools/qt_pdf_export.py`
與 `tests/test_ticket_print.py` 少數需要真實 matplotlib Figure 的測試）。
產品路徑（`tabs/tab_print.py::generate_pages()`）完全不 import 本檔，
`lib/` 底下任何檔案也不得 import 本檔或 matplotlib——這是
`tools/check_no_matplotlib.py` 要證明的事。

行為與階段 1／2 的 `MatplotlibCanvas` 完全相同，只是換了檔案位置；
唯一的差異是 `tabs/tab_print.py::fp()` 現在回傳輕量的 `FontSpec`
（`.path`／`.size`／`.bold`，不依賴 matplotlib），本檔的 `text()` 內部
自行把它轉成真正的 `matplotlib.font_manager.FontProperties`
（`fname=spec.path, size=spec.size`）——`fp()` 回傳值本身已經是依
`bold` 選好路徑（`_REG`／`_BOLD`）的結果，這裡不需要再看 `.bold`。
"""

from matplotlib import patches
from matplotlib.transforms import Bbox, TransformedBbox

from lib.print_canvas import A4_H_IN, A4_W_IN, Canvas


class MatplotlibCanvas(Canvas):
    """把 Canvas 呼叫轉成 ax.text／ax.add_patch(Rectangle)／ax.plot。

    ⚠️ `_draw_page()` 原本用 `FancyBboxPatch(boxstyle='square,pad=0')`
    畫矩形，`drawTicketPage()` 用 `Rectangle`；兩者在 `boxstyle='square,
    pad=0'`（無圓角、無內距）下是同一個矩形路徑，兩種呼叫方式繪出的像素
    相同，故這裡統一只用 `Rectangle`（也是 `test_ticket_palette_and_
    flat_single_line_artists` 對罰單頁的既有要求：不得出現 FancyBboxPatch）。

    `transform=ax.transAxes` 由本類別統一補上，呼叫端不再出現。
    """

    def __init__(self, fig, ax, fp):
        self.fig = fig
        self.ax = ax
        self._fp = fp

    def text(self, x, y, s, *, size, bold=False, ha='left', va='center',
             color='#111111', linespacing=None, multialignment=None,
             clip_rect=None):
        from matplotlib.font_manager import FontProperties
        spec = self._fp(size, bold=bold)
        prop = FontProperties(fname=spec.path, size=spec.size)
        extra = {}
        if linespacing is not None:
            extra['linespacing'] = linespacing
        if multialignment is not None:
            extra['multialignment'] = multialignment
        t = self.ax.text(
            x, y, s, fontproperties=prop, ha=ha, va=va,
            transform=self.ax.transAxes, color=color,
            clip_on=clip_rect is not None, **extra)
        if clip_rect is not None:
            x0, y0, x1, y1 = clip_rect
            t.set_clip_box(TransformedBbox(
                Bbox.from_extents(x0, y0, x1, y1), self.ax.transAxes))
            t.set_clip_on(True)
        return t

    def rect(self, x, y, w, h, *, facecolor=None, edgecolor=None,
             linewidth=0, zorder=1):
        p = patches.Rectangle(
            (x, y), w, h,
            linewidth=linewidth,
            edgecolor=edgecolor if edgecolor is not None else 'none',
            facecolor=facecolor if facecolor is not None else 'none',
            transform=self.ax.transAxes, zorder=zorder)
        self.ax.add_patch(p)
        return p

    def line(self, x0, y0, x1, y1, *, color, linewidth, zorder=2):
        return self.ax.plot(
            [x0, x1], [y0, y1], color=color, lw=linewidth, zorder=zorder,
            transform=self.ax.transAxes)


def new_mpl_page(fp):
    """建立一頁空白 A4 matplotlib figure／axes，回傳 `(fig, MatplotlibCanvas)`。
    `fp`：呼叫端注入的字型工廠（`tabs/tab_print.py::fp()`），簽章為
    `fp(size, bold=False) -> FontSpec`。呼叫端負責 `plt.close(fig)`。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(A4_W_IN, A4_H_IN))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor('white')
    return fig, MatplotlibCanvas(fig, ax, fp)


# ── matplotlib 字型度量（原 tabs/tab_print.py::_mpl_text_width_pt）───────
_MEASURE_RENDERER = None


def mpl_text_width_pt(text, font_spec):
    """以 matplotlib 實際字型度量回傳字串寬度(pt)。用 dpi=72 的
    RendererAgg → 回傳像素數即等於點數（pt）。`font_spec`：
    `tabs/tab_print.py::fp()` 回傳的 `FontSpec`（`.path`／`.size`）。"""
    global _MEASURE_RENDERER
    if _MEASURE_RENDERER is None:
        from matplotlib.backends.backend_agg import RendererAgg
        _MEASURE_RENDERER = RendererAgg(1, 1, 72)
    from matplotlib.font_manager import FontProperties
    prop = FontProperties(fname=font_spec.path, size=font_spec.size)
    w, _h, _d = _MEASURE_RENDERER.get_text_width_height_descent(
        text or "", prop, False)
    return w
