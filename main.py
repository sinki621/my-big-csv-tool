# DASH — User-Friendly (PyQt6) — no checkboxes, color-based selection, per-series downsampling
# - Linear / Log / Normalize (default Linear, markers ON)
# - UTC→KST, DateAxis(KST), Jump-to-Range
# - CSV/TSV/DAT robust parse (sep=None fallback), drop rows with all-nonfinite
# - Safe manual auto-fit (F / same as A)
# - Keys: L/G/N/A/D/F, ? = Help
# - Added:
#   • ProgressBar, Clipboard copy (Info/Plot)
#   • Centered mouse wheel zoom (Qt5/Qt6 compatible)
#   • Per-series Conditions (> / < / Δ%) with results list + event lines
#   • Threshold horizontal lines
#   • Region Highlight (toggle → click twice)
#   • Event/Note add (E), Bookmarks (B)
#   • Compare overlay (second file)
#   • Left Scratchpad (free note)
#
# NOTE: Original features remain; new features are additive only.

import os
os.environ["PYQTGRAPH_QT_LIB"] = "PyQt6"
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QT_WIDGETS_HIGDPI", "1")

import sys, csv, numpy as np, pandas as pd
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

# Optional Polars
try:
    import polars as pl
    HAS_POLARS = True
except Exception:
    HAS_POLARS = False

# Timezone
try:
    from zoneinfo import ZoneInfo
    KST = ZoneInfo("Asia/Seoul")
except Exception:
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9), name="KST")

TIME_COL = "Date UTC"
TIME_COL_CANDIDATES = ["Date UTC","UTC","Timestamp","DateTime","Datetime","Date_Time","Date","Time","time","date","datetime"]

pg.setConfigOptions(antialias=False, useOpenGL=False)

def sniff_delimiter_quick(path, sample_bytes=32768):
    try:
        with open(path, 'rb') as f:
            text = f.read(sample_bytes).decode('utf-8', errors='ignore')
        dialect = csv.Sniffer().sniff(text, delimiters=",\t;| ")
        d = dialect.delimiter
        return '\t' if (d == ' ' and text.count('\t') > text.count(' ')) else d
    except Exception:
        ext = os.path.splitext(path)[1].lower()
        return None if ext in ['.tsv', '.dat'] else ','

def is_numeric_polars_dtype(dt):
    try:
        if hasattr(dt, "is_numeric") and dt.is_numeric(): return True
        dec = getattr(pl, "Decimal", tuple())
        numeric_types = (pl.Int8,pl.Int16,pl.Int32,pl.Int64,pl.UInt8,pl.UInt16,pl.UInt32,pl.UInt64,pl.Float32,pl.Float64)
        return (dt in numeric_types) or (dec and dt == dec)
    except Exception:
        return False

def unit_from_name(name: str) -> str:
    n = name.lower()
    mapping = [
        ("_temp", "°C"), ("temperature", "°C"),
        ("_volt", "V"),  ("voltage", "V"),
        ("_curr", "A"),  ("current", "A"),
        ("_press","Pa"), ("pressure","Pa"),
        ("_flow","sccm"),("flow","sccm"),
        ("_rpm","rpm"),
        ("_freq","Hz"),  ("frequency","Hz"),
        ("_power","W"),  ("power","W"),
        ("_hum","%"),    ("humidity","%"),
    ]
    for key, u in mapping:
        if key in n:
            return u
    return ""

# ---------- Qt5/Qt6 호환: QDateTime -> python datetime ----------
def _qdatetime_to_py(dt: QtCore.QDateTime):
    # PyQt6 에서 보통 제공
    if hasattr(dt, "toPyDateTime"):
        return dt.toPyDateTime()
    # Fallback: epoch msecs
    msecs = dt.toMSecsSinceEpoch()
    return pd.Timestamp(msecs/1000.0, unit='s', tz=KST).tz_convert(None).to_pydatetime()

# ---------- Centered ViewBox (Qt5/Qt6 wheel compat) ----------
class CenteredViewBox(pg.ViewBox):
    def wheelEvent(self, ev):
        # wheel delta compat
        def _delta(e):
            if hasattr(e, "angleDelta"):
                ad = e.angleDelta()
                return ad.y() if hasattr(ad, "y") else (ad[1] if isinstance(ad, (tuple, list)) else 0)
            if hasattr(e, "delta"):
                return e.delta()
            return 0

        # scene pos compat
        if hasattr(ev, "scenePosition"):
            sp = ev.scenePosition()
        elif hasattr(ev, "scenePos"):
            sp = ev.scenePos()
        else:
            sp = ev.pos()

        d = _delta(ev)
        if d == 0:
            ev.ignore(); return

        anchor = self.mapSceneToView(sp)
        s = 0.9 if d > 0 else 1.111111

        mods = ev.modifiers() if hasattr(ev, "modifiers") else QtCore.Qt.KeyboardModifier.NoModifier
        if mods & QtCore.Qt.KeyboardModifier.ControlModifier:
            self._zoom_around(anchor, 1.0, s)   # Y only
        elif mods & QtCore.Qt.KeyboardModifier.ShiftModifier:
            self._zoom_around(anchor, s, 1.0)   # X only
        else:
            self._zoom_around(anchor, s, s)     # XY
        ev.accept()

    def _zoom_around(self, anchor, sx, sy):
        xr, yr = self.viewRange()
        ax, ay = anchor.x(), anchor.y()
        x0, x1 = xr; y0, y1 = yr
        nx0 = ax - (ax - x0)*sx; nx1 = ax + (x1 - ax)*sx
        ny0 = ay - (ay - y0)*sy; ny1 = ay + (y1 - ay)*sy
        self.setRange(xRange=(nx0, nx1), yRange=(ny0, ny1), padding=0.0)

# ---------- per-series Condition dialog ----------
class ConditionDialog(QtWidgets.QDialog):
    def __init__(self, series_name, parent=None, preset=None):
        super().__init__(parent)
        self.setWindowTitle(f"Conditions — {series_name}")
        self.setModal(True)
        lay = QtWidgets.QFormLayout(self)
        self.chk_gt = QtWidgets.QCheckBox("Value >"); self.ed_gt  = QtWidgets.QDoubleSpinBox(); self.ed_gt.setDecimals(6); self.ed_gt.setRange(-1e300, 1e300)
        self.chk_lt = QtWidgets.QCheckBox("Value <"); self.ed_lt  = QtWidgets.QDoubleSpinBox(); self.ed_lt.setDecimals(6); self.ed_lt.setRange(-1e300, 1e300)
        self.chk_dp = QtWidgets.QCheckBox("Δ% ≥");     self.ed_dp  = QtWidgets.QDoubleSpinBox(); self.ed_dp.setDecimals(3); self.ed_dp.setRange(0.0, 1e9)
        if preset:
            if 'gt' in preset: self.chk_gt.setChecked(True); self.ed_gt.setValue(float(preset['gt']))
            if 'lt' in preset: self.chk_lt.setChecked(True); self.ed_lt.setValue(float(preset['lt']))
            if 'deltapct' in preset: self.chk_dp.setChecked(True); self.ed_dp.setValue(float(preset['deltapct']))
        h1 = QtWidgets.QHBoxLayout(); h1.addWidget(self.chk_gt); h1.addWidget(self.ed_gt)
        h2 = QtWidgets.QHBoxLayout(); h2.addWidget(self.chk_lt); h2.addWidget(self.ed_lt)
        h3 = QtWidgets.QHBoxLayout(); h3.addWidget(self.chk_dp); h3.addWidget(self.ed_dp)
        cont = QtWidgets.QWidget(); v = QtWidgets.QVBoxLayout(cont); v.addLayout(h1); v.addLayout(h2); v.addLayout(h3)
        lay.addRow(cont)
        btn_ok = QtWidgets.QPushButton("OK"); btn_cancel = QtWidgets.QPushButton("Cancel")
        btns = QtWidgets.QHBoxLayout(); btns.addStretch(1); btns.addWidget(btn_cancel); btns.addWidget(btn_ok)
        lay.addRow(btns)
        btn_ok.clicked.connect(self.accept); btn_cancel.clicked.connect(self.reject)

    def result_rules(self):
        res = {}
        if self.chk_gt.isChecked(): res['gt'] = float(self.ed_gt.value())
        if self.chk_lt.isChecked(): res['lt'] = float(self.ed_lt.value())
        if self.chk_dp.isChecked(): res['deltapct'] = float(self.ed_dp.value())
        return res

class DASH(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DASH — Data Viewer (PyQt6)")
        self.resize(1580, 900)

        # data
        self.series_cols = []
        self.time_col = TIME_COL
        self.x_sec = None; self.x_ns = None
        self.Y_raw = {}; self.Y_norm = {}
        self.curves = {}

        # state
        self.current_mode = "linear"
        self.markers_on = True

        # per-series downsampling flags + global default
        self.ds_for = {}
        self.ds_default = True

        # Active/Inactive
        self.active_for = {}

        # new states
        self.thresholds = {}        # {col: [{'op':'=','value':float,'line':item,'label':item}]}
        self.find_rules = {}        # {col: {'gt':v,'lt':v,'deltapct':v}}
        self.event_items = []       # [{'x_ns':int,'line':item,'label':item,'series':str,'text':str}]
        self.highlight_regions = [] # [{'reg':LinearRegionItem,'text':str}]
        self.highlight_mode = False
        self.highlight_first_ns = None
        self.bookmarks = []         # [(x_ns,label)]
        self.compare_mode = False
        self.compare_data = None
        self.curves_ref = {}

        # ---- UI ----
        top = QtWidgets.QWidget(); self.setCentralWidget(top)
        vbox = QtWidgets.QVBoxLayout(top); vbox.setContentsMargins(6,6,6,6); vbox.setSpacing(6)

        # Top bar
        topbar = QtWidgets.QHBoxLayout(); vbox.addLayout(topbar)
        self.path_edit = QtWidgets.QLineEdit(); self.path_edit.setPlaceholderText("CSV/TSV/DAT file path"); self.path_edit.setReadOnly(True)
        btn_browse = QtWidgets.QPushButton("Open"); btn_browse.clicked.connect(self.browse_file)

        self.start_date = QtWidgets.QDateEdit(calendarPopup=True); self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_time = QtWidgets.QTimeEdit(); self.start_time.setDisplayFormat("HH:mm:ss")
        self.end_date   = QtWidgets.QDateEdit(calendarPopup=True); self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_time   = QtWidgets.QTimeEdit(); self.end_time.setDisplayFormat("HH:mm:ss")
        self.chk_full   = QtWidgets.QCheckBox("Full Range"); self.chk_full.setChecked(True)
        btn_load = QtWidgets.QPushButton("Load"); btn_load.clicked.connect(self.load_and_plot)

        btn_help = QtWidgets.QPushButton("?"); btn_help.setToolTip("Shortcuts Help"); btn_help.clicked.connect(self.show_help)
        self.btn_ds_global = QtWidgets.QPushButton("Downsampling: ON")
        self.btn_ds_global.setCheckable(True); self.btn_ds_global.setChecked(True)
        self.btn_ds_global.clicked.connect(self.toggle_ds_global)

        # new: Compare & Highlight
        self.btn_compare = QtWidgets.QPushButton("Compare: OFF"); self.btn_compare.setCheckable(True); self.btn_compare.clicked.connect(self.toggle_compare_mode)
        self.btn_open_ref = QtWidgets.QPushButton("Open Ref"); self.btn_open_ref.clicked.connect(self.open_compare_file); self.btn_open_ref.setEnabled(False)
        self.btn_highlight = QtWidgets.QPushButton("Highlight: OFF"); self.btn_highlight.setCheckable(True); self.btn_highlight.clicked.connect(self.toggle_highlight_mode)

        topbar.addWidget(QtWidgets.QLabel("File")); topbar.addWidget(self.path_edit, 1); topbar.addWidget(btn_browse)
        topbar.addSpacing(10)
        topbar.addWidget(QtWidgets.QLabel("Start")); topbar.addWidget(self.start_date); topbar.addWidget(self.start_time)
        topbar.addSpacing(6)
        topbar.addWidget(QtWidgets.QLabel("End"));   topbar.addWidget(self.end_date);   topbar.addWidget(self.end_time)
        topbar.addSpacing(8); topbar.addWidget(self.chk_full); topbar.addSpacing(8); topbar.addWidget(btn_load)
        topbar.addSpacing(10); topbar.addWidget(self.btn_ds_global)
        topbar.addSpacing(10); topbar.addWidget(self.btn_compare); topbar.addWidget(self.btn_open_ref)
        topbar.addSpacing(10); topbar.addWidget(self.btn_highlight); topbar.addWidget(btn_help)

        # Middle splitter
        hsplit = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal); vbox.addWidget(hsplit, 1)

        # Left panel
        left = QtWidgets.QWidget(); left_v = QtWidgets.QVBoxLayout(left); left_v.setContentsMargins(6,6,6,6); left_v.setSpacing(8)
        grp_scale = QtWidgets.QGroupBox("Y Scale"); rb_lay = QtWidgets.QHBoxLayout(grp_scale)
        self.rb_linear = QtWidgets.QRadioButton("linear"); self.rb_linear.setChecked(True)
        self.rb_log    = QtWidgets.QRadioButton("log")
        self.rb_norm   = QtWidgets.QRadioButton("normalize")
        for rb in (self.rb_linear, self.rb_log, self.rb_norm):
            rb_lay.addWidget(rb); rb.toggled.connect(self.on_scale_changed)
        left_v.addWidget(grp_scale)

        grp_jump = QtWidgets.QGroupBox("Jump to Range (KST)")
        gl = QtWidgets.QGridLayout(grp_jump)
        self.dt_start = QtWidgets.QDateTimeEdit(); self.dt_start.setDisplayFormat("yyyy-MM-dd HH:mm:ss"); self.dt_start.setCalendarPopup(True)
        self.dt_end   = QtWidgets.QDateTimeEdit(); self.dt_end.setDisplayFormat("yyyy-MM-dd HH:mm:ss"); self.dt_end.setCalendarPopup(True)
        self.btn_jump = QtWidgets.QPushButton("Go"); self.btn_jump.clicked.connect(self.go_to_range)
        self.dt_start.setEnabled(False); self.dt_end.setEnabled(False); self.btn_jump.setEnabled(False)
        gl.addWidget(QtWidgets.QLabel("Start"), 0, 0); gl.addWidget(self.dt_start, 0, 1)
        gl.addWidget(QtWidgets.QLabel("End"),   1, 0); gl.addWidget(self.dt_end,   1, 1)
        gl.addWidget(self.btn_jump, 2, 1)
        left_v.addWidget(grp_jump)

        self.cmb_time_col = QtWidgets.QComboBox(); self.cmb_time_col.setVisible(False)
        self.cmb_time_col.currentTextChanged.connect(self.on_time_col_changed)
        left_v.addWidget(self.cmb_time_col)

        self.info = QtWidgets.QPlainTextEdit(); self.info.setReadOnly(True)
        mono = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont); mono.setPointSize(10)
        self.info.setFont(mono); self.info.setPlainText("Load a file to see diagnostics here.")
        left_v.addWidget(self.info, 1)

        # new: Scratchpad (free note)
        grp_notes = QtWidgets.QGroupBox("Notes (Scratchpad)")
        notes_l = QtWidgets.QVBoxLayout(grp_notes)
        self.scratch = QtWidgets.QPlainTextEdit()
        notes_l.addWidget(self.scratch)
        left_v.addWidget(grp_notes, 1)

        # new: Bookmarks
        grp_bm = QtWidgets.QGroupBox("Bookmarks")
        bm_l = QtWidgets.QVBoxLayout(grp_bm)
        self.list_bm = QtWidgets.QListWidget()
        row_bm_btn = QtWidgets.QHBoxLayout()
        btn_bm_add = QtWidgets.QPushButton("Add"); btn_bm_go = QtWidgets.QPushButton("Go"); btn_bm_del = QtWidgets.QPushButton("Del")
        row_bm_btn.addWidget(btn_bm_add); row_bm_btn.addWidget(btn_bm_go); row_bm_btn.addWidget(btn_bm_del)
        bm_l.addWidget(self.list_bm); bm_l.addLayout(row_bm_btn)
        left_v.addWidget(grp_bm)
        btn_bm_add.clicked.connect(self.add_bookmark_dialog)
        btn_bm_go.clicked.connect(self.jump_bookmark)
        btn_bm_del.clicked.connect(self.del_bookmark)
        self.list_bm.itemDoubleClicked.connect(lambda it: self.jump_bookmark())

        # Plot (CenteredViewBox)
        axis = pg.DateAxisItem(utcOffset=9*3600)
        self.viewbox = CenteredViewBox()
        self.plot = pg.PlotWidget(viewBox=self.viewbox, axisItems={'bottom': axis})
        self.plot.setBackground('w'); self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.enableAutoRange(x=False, y=False)
        self.plot.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.plot.setCacheMode(QtWidgets.QGraphicsView.CacheModeFlag.CacheNone)
        self.plot.setRenderHints(QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing)
        self.view = self.plot.getPlotItem().vb
        self._set_min_ranges()

        # crosshair + hover readout
        self.vline = pg.InfiniteLine(angle=90, movable=False,
                                     pen=pg.mkPen((100,100,100,120), width=1, style=QtCore.Qt.PenStyle.DashLine))
        self.plot.addItem(self.vline)
        self.plot.scene().sigMouseMoved.connect(self.on_mouse_moved)
        self.plot.scene().sigMouseClicked.connect(self.on_plot_clicked)

        # Right panel
        right = QtWidgets.QWidget(); right_v = QtWidgets.QVBoxLayout(right); right_v.setContentsMargins(6,6,6,6); right_v.setSpacing(8)

        # quick filter
        filter_row = QtWidgets.QHBoxLayout()
        self.ed_filter = QtWidgets.QLineEdit(); self.ed_filter.setPlaceholderText("Filter series (e.g., temp, volt)")
        self.ed_filter.textChanged.connect(self.apply_series_filter)
        filter_row.addWidget(QtWidgets.QLabel("Search")); filter_row.addWidget(self.ed_filter, 1)
        right_v.addLayout(filter_row)

        # series list (no checkboxes)
        self.list_series = QtWidgets.QListWidget()
        self.list_series.setAlternatingRowColors(True)
        self.list_series.setUniformItemSizes(True)
        self.list_series.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self.list_series.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_series.setStyleSheet(
            "QListView{background:#f8f8f8;color:#111;border:1px solid #ddd;}"
            "QListView::item{height:22px;padding-left:8px;}"
        )
        self.list_series.itemClicked.connect(self.on_item_clicked)
        self.list_series.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_series.customContextMenuRequested.connect(self.on_series_context_menu)
        right_v.addWidget(self.list_series, 1)

        # selection control row (All On/Off/Invert)
        sel_row = QtWidgets.QHBoxLayout()
        self.btn_all_on  = QtWidgets.QPushButton("All On");  self.btn_all_on.clicked.connect(self.select_all_on)
        self.btn_all_off = QtWidgets.QPushButton("All Off"); self.btn_all_off.clicked.connect(self.select_all_off)
        self.btn_invert  = QtWidgets.QPushButton("Invert");  self.btn_invert.clicked.connect(self.select_invert)
        sel_row.addWidget(self.btn_all_on); sel_row.addWidget(self.btn_all_off); sel_row.addWidget(self.btn_invert)
        right_v.addLayout(sel_row)

        # debug + export
        r1 = QtWidgets.QHBoxLayout()
        self.btn_first_only = QtWidgets.QPushButton("Show 1st Only"); self.btn_first_only.clicked.connect(self.show_first_only)
        self.chk_markers = QtWidgets.QCheckBox("Markers"); self.chk_markers.setChecked(True); self.chk_markers.toggled.connect(self.toggle_markers)
        r1.addWidget(self.btn_first_only); r1.addWidget(self.chk_markers); right_v.addLayout(r1)

        # conditions
        row_cond = QtWidgets.QHBoxLayout()
        self.btn_run_cond = QtWidgets.QPushButton("Run Conditions"); self.btn_run_cond.clicked.connect(self.run_event_finder)
        row_cond.addWidget(self.btn_run_cond); right_v.addLayout(row_cond)
        self.list_events = QtWidgets.QListWidget()
        self.list_events.setMinimumHeight(120)
        self.list_events.itemDoubleClicked.connect(self.jump_event_item)
        right_v.addWidget(QtWidgets.QLabel("Condition Results")); right_v.addWidget(self.list_events, 0)

        # Export / Copy
        r2 = QtWidgets.QHBoxLayout()
        self.btn_dump = QtWidgets.QPushButton("Dump Diagnostics"); self.btn_dump.clicked.connect(self._dump_diagnostics)
        self.btn_export_csv = QtWidgets.QPushButton("Export CSV (visible range)"); self.btn_export_csv.clicked.connect(self.export_visible_csv)
        self.btn_export_png = QtWidgets.QPushButton("Export PNG (plot)"); self.btn_export_png.clicked.connect(self.export_plot_png)
        r2.addWidget(self.btn_dump); right_v.addLayout(r2)
        r3 = QtWidgets.QHBoxLayout()
        r3.addWidget(self.btn_export_csv); r3.addWidget(self.btn_export_png)
        right_v.addLayout(r3)

        left.setMinimumWidth(360); right.setMinimumWidth(420)
        hsplit.addWidget(left); hsplit.addWidget(self.plot); hsplit.addWidget(right)
        hsplit.setSizes([380, 860, 420])

        self.status = self.statusBar(); self.status.showMessage("Ready")
        # Progress + Copy
        self.progress = QtWidgets.QProgressBar(); self.progress.setMaximumHeight(14)
        self.progress.setRange(0, 100); self.progress.setValue(0); self.progress.setVisible(False)
        self.btn_copy_view = QtWidgets.QPushButton("Copy Plot"); self.btn_copy_view.clicked.connect(self.copy_plot_to_clipboard)
        self.btn_copy_info = QtWidgets.QPushButton("Copy Info"); self.btn_copy_info.clicked.connect(self.copy_info_to_clipboard)
        self.status.addPermanentWidget(self.progress); self.status.addPermanentWidget(self.btn_copy_info); self.status.addPermanentWidget(self.btn_copy_view)

        # Shortcuts
        QtGui.QShortcut(QtGui.QKeySequence("L"), self, activated=lambda: self.set_scale("linear"))
        QtGui.QShortcut(QtGui.QKeySequence("G"), self, activated=lambda: self.set_scale("log"))
        QtGui.QShortcut(QtGui.QKeySequence("N"), self, activated=lambda: self.set_scale("normalize"))
        sc_fit = QtGui.QShortcut(QtGui.QKeySequence("F"), self); sc_fit.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut); sc_fit.activated.connect(self._fit_view)
        QtGui.QShortcut(QtGui.QKeySequence("A"), self, activated=self.select_all_on)
        QtGui.QShortcut(QtGui.QKeySequence("D"), self, activated=self.select_all_off)
        QtGui.QShortcut(QtGui.QKeySequence("?"), self, activated=self.show_help)
        QtGui.QShortcut(QtGui.QKeySequence("E"), self, activated=self.add_event_at_cursor)
        QtGui.QShortcut(QtGui.QKeySequence("B"), self, activated=self.add_bookmark_dialog)

        # drag & drop open
        self.setAcceptDrops(True)

        # pens
        self.pen_active_cache = {}
        self.pen_inactive = pg.mkPen((150,150,150,120), width=1.0)
        self.opacity_active = 1.0
        self.opacity_inactive = 0.20

    # ------------ drag & drop ------------
    def dragEnterEvent(self, e: QtGui.QDragEnterEvent):
        if e.mimeData().hasUrls(): e.acceptProposedAction()

    def dropEvent(self, e: QtGui.QDropEvent):
        urls = e.mimeData().urls()
        if not urls: return
        path = urls[0].toLocalFile()
        if path:
            self.path_edit.setText(path); self.load_and_plot()

    # ------------ utils ------------
    def _set_min_ranges(self):
        try: self.view.setLimits(minXRange=1.0, minYRange=1e-6)
        except Exception: pass

    def set_scale(self, mode):
        if mode == "linear": self.rb_linear.setChecked(True)
        elif mode == "log":  self.rb_log.setChecked(True)
        else:                 self.rb_norm.setChecked(True)
        self.on_scale_changed()

    # ------------ file ------------
    def browse_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Data File", "", "Data Files (*.csv *.tsv *.dat);;All Files (*)")
        if path: self.path_edit.setText(path)

    # ------------ load + plot ------------
    def load_and_plot(self):
        path = self.path_edit.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, "Notice", "Please select a data file."); return
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.critical(self, "Error", "File does not exist."); return

        start_dt = end_dt = None
        if not self.chk_full.isChecked():
            try:
                sd = self.start_date.date().toPyDate(); st = self.start_time.time().toPyTime()
                ed = self.end_date.date().toPyDate();   et = self.end_time.time().toPyTime()
                if sd: start_dt = pd.Timestamp.combine(sd, st).tz_localize(KST)
                if ed: end_dt   = pd.Timestamp.combine(ed, et).tz_localize(KST)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Time Error", f"Failed to parse time: {e}"); return

        self.progress.setVisible(True); self.progress.setValue(5); self.status.showMessage("Loading...")
        QtWidgets.QApplication.processEvents()

        try:
            self._read_and_prepare(path, start_dt, end_dt)
            self.progress.setValue(60); QtWidgets.QApplication.processEvents()
        except Exception as e:
            self.progress.setVisible(False); self.status.showMessage("Error")
            QtWidgets.QMessageBox.critical(self, "Load Error", str(e)); return

        self._plot_all()
        self.progress.setValue(90); QtWidgets.QApplication.processEvents()
        self._fit_view()
        self.progress.setValue(100)
        QtCore.QTimer.singleShot(250, lambda: (self.progress.setVisible(False), self.status.showMessage(
            f"Loaded: {os.path.basename(self.path_edit.text())} / series={len(self.series_cols)} / points={len(self.x_sec)} / time={self.time_col}")))

    def _read_and_prepare(self, path, start_dt, end_dt):
        delim = sniff_delimiter_quick(path)
        if HAS_POLARS:
            df = pl.read_csv(path, infer_schema_length=10000, has_header=True) if delim is None else \
                 pl.read_csv(path, infer_schema_length=10000, separator=delim, has_header=True)
            tcol = next((c for c in TIME_COL_CANDIDATES if c in df.columns), df.columns[0])
            self.time_col = tcol
            ts_expr = pl.col(self.time_col).str.strptime(pl.Datetime, strict=False, exact=False)
            df = df.with_columns([ts_expr.alias("_ts_").dt.replace_time_zone("UTC").dt.convert_time_zone("Asia/Seoul")]) \
                   .drop_nulls(["_ts_"]).sort("_ts_")
            if start_dt or end_dt:
                sdt = start_dt.to_pydatetime() if start_dt is not None else None
                edt = end_dt.to_pydatetime()   if end_dt   is not None else None
                if sdt and edt: df = df.filter((pl.col("_ts_") >= sdt) & (pl.col("_ts_") <= edt))
                elif sdt:       df = df.filter(pl.col("_ts_") >= sdt)
                elif edt:       df = df.filter(pl.col("_ts_") <= edt)
            num_cols = [c for c, dt in zip(df.columns, df.dtypes) if c not in (self.time_col, "_ts_") and is_numeric_polars_dtype(dt)]
            if not num_cols: raise ValueError("No numeric series to plot.")
            x_ns  = df["_ts_"].dt.timestamp("ns").to_numpy().astype("int64", copy=False)
            x_sec = x_ns.astype("float64") / 1e9
            Y_raw = {col: df[col].to_numpy().astype("float64", copy=False) for col in num_cols}
        else:
            df = pd.read_csv(path, sep=delim) if delim is not None else pd.read_csv(path, sep=None, engine="python")
            tcol = next((c for c in TIME_COL_CANDIDATES if c in df.columns), df.columns[0])
            self.time_col = tcol
            ts = pd.to_datetime(df[self.time_col], errors="coerce").dt.tz_localize("UTC").dt.tz_convert(KST)
            df = df.assign(_ts_=ts).dropna(subset=["_ts_"]).sort_values("_ts_")
            if start_dt or end_dt:
                sdt = start_dt if start_dt is not None else df["_ts_"].min()
                edt = end_dt   if end_dt   is not None else df["_ts_"].max()
                df = df[(df["_ts_"] >= sdt) & (df["_ts_"] <= edt)]
            num_cols = [c for c in df.columns if c not in (self.time_col, "_ts_") and pd.api.types.is_numeric_dtype(df[c])]
            if not num_cols: raise ValueError("No numeric series to plot.")
            x_ns  = df["_ts_"].view("int64").to_numpy()
            x_sec = x_ns.astype("float64") / 1e9
            Y_raw = {col: pd.to_numeric(df[col], errors='coerce').to_numpy(dtype="float64", copy=False) for col in num_cols}

        # normalize & valid rows
        Y_norm = {}
        for col, y in Y_raw.items():
            ymin = np.nanmin(y); ymax = np.nanmax(y)
            Y_norm[col] = (y - ymin) / (ymax - ymin) if np.isfinite(ymin) and np.isfinite(ymax) and ymax > ymin else np.zeros_like(y)

        if num_cols:
            finite_mask = np.vstack([np.isfinite(Y_raw[c]) for c in num_cols])
            valid_row = finite_mask.any(axis=0)
        else:
            valid_row = np.array([], dtype=bool)

        x_ns = x_ns[valid_row]; x_sec = x_sec[valid_row]
        for c in list(Y_raw.keys()):
            Y_raw[c]  = Y_raw[c][valid_row]; Y_norm[c] = Y_norm[c][valid_row]

        self.series_cols = num_cols
        self.x_ns = x_ns; self.x_sec = x_sec
        self.Y_raw = Y_raw; self.Y_norm = Y_norm

        # init states / clear overlays
        self.ds_for = {c: self.ds_default for c in self.series_cols}
        self.active_for = {}
        self.thresholds = {}
        self.find_rules = {}
        self.event_items.clear()
        self.highlight_regions.clear()
        self.compare_data = None; self.curves_ref.clear()

        self._maybe_show_time_selector(path, delim)

    def _maybe_show_time_selector(self, path, delim):
        try:
            hdr = (pd.read_csv(path, nrows=0, sep=None, engine="python").columns.tolist()
                   if delim is None else
                   [h.strip() for h in open(path, 'r', encoding='utf-8', errors='ignore').readline().strip().split(delim)])
        except Exception:
            hdr = []
        cands = [h for h in hdr if h in TIME_COL_CANDIDATES]
        if cands and self.time_col in cands and len(cands) > 1:
            self.cmb_time_col.clear(); self.cmb_time_col.addItems(cands)
            self.cmb_time_col.setCurrentText(self.time_col); self.cmb_time_col.setVisible(True)
        else:
            self.cmb_time_col.setVisible(False)

    # ------------ scale ------------
    def on_scale_changed(self):
        self.current_mode = "linear" if self.rb_linear.isChecked() else ("log" if self.rb_log.isChecked() else "normalize")
        pi = self.plot.getPlotItem()
        pi.setLogMode(x=False, y=(self.current_mode == "log"))
        self._update_curves_for_mode()
        if self.current_mode == "normalize":
            pi.setYRange(0, 1, padding=0.02)
        self.plot.enableAutoRange(x=False, y=False)
        self._refresh_legend()
        self._update_left_axis_label()
        self._fit_view()
        self._set_min_ranges()

    def _update_curves_for_mode(self):
        for col, cv in self.curves.items():
            y = self.Y_raw[col]
            if self.current_mode == "normalize":
                y_disp = self.Y_norm[col]; connect_mode = 'all'
            elif self.current_mode == "log":
                y_disp = np.where(np.isfinite(y) & (np.abs(y) > 0), np.abs(y), np.nan); connect_mode = 'finite'
            else:
                y_disp = np.where(np.isfinite(y), y, np.nan); connect_mode = 'all'
            try: cv.setData(self.x_sec, y_disp, connect=connect_mode)
            except Exception: cv.setData(self.x_sec, y_disp)
            try:
                cv.setClipToView(self.ds_for.get(col, self.ds_default))
                cv.setDownsampling(auto=self.ds_for.get(col, self.ds_default))
            except Exception: pass
            self._apply_symbol(cv)
        self._dump_diagnostics(include_original_range=(self.current_mode=="normalize"))

    def _update_left_axis_label(self):
        visible_active = [c for c, a in self.active_for.items() if a]
        ax = self.plot.getAxis('left')
        if self.current_mode == "normalize":
            ax.setLabel(text="Normalized"); return
        if not visible_active:
            ax.setLabel(text="Y"); return
        units = set(unit_from_name(c) for c in visible_active)
        if len(units) == 1:
            u = next(iter(units)); ax.setLabel(text=("Value" if u=="" else u))
        else:
            ax.setLabel(text="Mixed")

    # ------------ fit ------------
    def _fit_view(self):
        if self.x_sec is None or len(self.x_sec) == 0: return
        pi = self.plot.getPlotItem(); vb = pi.vb
        self.plot.enableAutoRange(x=True, y=True)
        try: pi.autoRange()
        finally: self.plot.enableAutoRange(x=False, y=False)
        try:
            xr, yr = vb.viewRange()
            pad_x = 0.02 * (xr[1] - xr[0]) if xr[1] > xr[0] else 0.0
            pad_y = 0.02 * (yr[1] - yr[0]) if yr[1] > yr[0] else 0.0
            if self.current_mode == "log":
                y0 = max(yr[0] - pad_y, 1e-12); y1 = yr[1] + pad_y
            else:
                y0 = yr[0] - pad_y; y1 = yr[1] + pad_y
            vb.setRange(xRange=(xr[0] - pad_x, xr[1] + pad_x), yRange=(y0, y1), padding=0.0)
        except Exception:
            pass

    # ------------ plot all ------------
    def _plot_all(self):
        self.plot.clear(); self.plot.addItem(self.vline)
        self.plot.setAxisItems({'bottom': pg.DateAxisItem(utcOffset=9*3600)})
        self.curves.clear()
        self.list_series.clear()
        self.list_events.clear()
        self.current_mode = "linear"; self.rb_linear.setChecked(True)

        if not self.series_cols:
            self.info.setPlainText("No numeric series."); return

        scores = {}
        for c in self.series_cols:
            y = self.Y_raw[c]; fin = y[np.isfinite(y)]
            scores[c] = -np.inf if fin.size==0 else 0.7*np.nanstd(fin) + 0.3*np.nanmax(np.abs(fin))
        ordered = sorted(self.series_cols, key=lambda c: scores[c], reverse=True)

        for i, col in enumerate(ordered):
            self.pen_active_cache[col] = pg.mkPen(pg.intColor(i, hues=max(8, len(ordered)), maxValue=255), width=2.2)

        init_show_n = min(6, len(ordered))
        for i, col in enumerate(ordered):
            cv = self.plot.plot(self.x_sec, self.Y_raw[col], name=col, pen=self.pen_active_cache[col])
            self.curves[col] = cv
            try:
                cv.setClipToView(self.ds_for.get(col, self.ds_default))
                cv.setDownsampling(auto=self.ds_for.get(col, self.ds_default))
            except Exception: pass
            self._apply_symbol(cv)
            self.active_for[col] = (i < init_show_n)

            it = QtWidgets.QListWidgetItem(col)
            it.setToolTip("Right-click: Conditions / Threshold / Color / Downsampling")
            self.list_series.addItem(it)

        self._apply_active_styles_to_curves_and_list()
        try: self.plot.addLegend(offset=(0,0))
        except Exception: pass
        self._refresh_legend()
        self._dump_diagnostics(include_original_range=False)
        self._update_left_axis_label()

        if self.x_sec is not None and len(self.x_sec) > 1:
            self._fit_view()
        if self.x_ns is not None and len(self.x_ns) > 0:
            self._enable_jump_controls(int(np.nanmin(self.x_ns)), int(np.nanmax(self.x_ns)))

        self.status.showMessage(
            f"Loaded: {os.path.basename(self.path_edit.text())} / series={len(self.series_cols)} "
            f"/ points={len(self.x_sec)} / time={self.time_col}"
        )

    # ------------ active/inactive handling ------------
    def _apply_active_styles_to_curves_and_list(self):
        for col, cv in self.curves.items():
            if self.active_for.get(col, True):
                cv.show()
                cv.setPen(self.pen_active_cache[col])
                try: cv.setOpacity(self.opacity_active)
                except Exception: pass
            else:
                cv.hide()
        for i in range(self.list_series.count()):
            it = self.list_series.item(i)
            col = it.text()
            it.setForeground(QtGui.QBrush(QtGui.QColor(20,20,20) if self.active_for.get(col, True) else QtGui.QColor(140,140,140)))
        self._refresh_legend()

    def on_item_clicked(self, item: QtWidgets.QListWidgetItem):
        col = item.text()
        self.active_for[col] = not self.active_for.get(col, True)
        self._apply_active_styles_to_curves_and_list()
        self._update_left_axis_label()
        self._fit_view()

    def select_all_on(self):
        for c in self.series_cols: self.active_for[c] = True
        self._apply_active_styles_to_curves_and_list(); self._update_left_axis_label(); self._fit_view()

    def select_all_off(self):
        for c in self.series_cols: self.active_for[c] = False
        self._apply_active_styles_to_curves_and_list(); self._update_left_axis_label(); self._fit_view()

    def select_invert(self):
        for c in self.series_cols: self.active_for[c] = not self.active_for.get(c, True)
        self._apply_active_styles_to_curves_and_list(); self._update_left_axis_label(); self._fit_view()

    def _refresh_legend(self):
        leg = self.plot.plotItem.legend
        if leg is None:
            try: self.plot.addLegend(offset=(0,0)); leg = self.plot.plotItem.legend
            except Exception: return
        leg.clear()
        for col, cv in self.curves.items():
            if self.active_for.get(col, True):
                try: leg.addItem(cv, col)
                except Exception: pass
        for col, cv in self.curves_ref.items():
            try: leg.addItem(cv, f"{col} (ref)")
            except Exception: pass

    def apply_series_filter(self, text: str):
        t = (text or "").lower().strip()
        for i in range(self.list_series.count()):
            it = self.list_series.item(i)
            it.setHidden(False if not t else (t not in it.text().lower()))

    # per-series context menu (Conditions / Threshold)
    def on_series_context_menu(self, pos):
        item = self.list_series.itemAt(pos)
        if not item: return
        col = item.text()
        menu = QtWidgets.QMenu(self)
        act_cond  = menu.addAction("Set Conditions…")
        act_thresh= menu.addAction("Add Threshold Line…")
        menu.addSeparator()
        act_toggle = menu.addAction(f"Toggle Downsampling for '{col}' ({'ON' if self.ds_for.get(col, self.ds_default) else 'OFF'})")
        act_color  = menu.addAction("Change Color…")
        action = menu.exec(self.list_series.mapToGlobal(pos))
        if action == act_toggle:
            self.ds_for[col] = not self.ds_for.get(col, self.ds_default)
            cv = self.curves.get(col)
            if cv:
                try: cv.setClipToView(self.ds_for[col]); cv.setDownsampling(auto=self.ds_for[col])
                except Exception: pass
        elif action == act_color:
            colr = QtWidgets.QColorDialog.getColor(parent=self, title=f"Choose color for {col}")
            if colr.isValid():
                self.pen_active_cache[col] = pg.mkPen(colr, width=2.2)
                if self.active_for.get(col, True): self.curves[col].setPen(self.pen_active_cache[col])
        elif action == act_cond:
            preset = self.find_rules.get(col, None)
            dlg = ConditionDialog(col, self, preset)
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                rules = dlg.result_rules()
                if rules: self.find_rules[col] = rules
                else: self.find_rules.pop(col, None)
        elif action == act_thresh:
            value, ok = QtWidgets.QInputDialog.getDouble(self, "Add Threshold", f"{col}  threshold value:", 0.0, -1e300, 1e300, 6)
            if ok:
                self.add_threshold_line(col, value)

    def toggle_ds_global(self):
        self.ds_default = self.btn_ds_global.isChecked()
        self.btn_ds_global.setText(f"Downsampling: {'ON' if self.ds_default else 'OFF'}")
        for col, cv in self.curves.items():
            self.ds_for[col] = self.ds_default
            try:
                cv.setClipToView(self.ds_default); cv.setDownsampling(auto=self.ds_default)
            except Exception: pass

    # ------------ markers & debug ------------
    def _apply_symbol(self, curve):
        if self.markers_on:
            try: curve.setSymbol('o'); curve.setSymbolSize(3); curve.setSymbolBrush(pg.mkBrush(0,0,0,80))
            except Exception: pass
        else:
            try: curve.setSymbol(None)
            except Exception: pass

    def show_first_only(self):
        if not self.series_cols: return
        best = None; best_val = -1
        for c in self.series_cols:
            y = self.Y_raw[c]; fin = np.abs(y[np.isfinite(y)])
            if fin.size == 0: continue
            m = float(np.nanmax(fin))
            if m > best_val: best_val = m; best = c
        if best is None: return
        for c in self.series_cols: self.active_for[c] = (c == best)
        self._apply_active_styles_to_curves_and_list(); self._update_left_axis_label(); self._fit_view()

    def toggle_markers(self, state):
        self.markers_on = bool(state)
        for cv in self.curves.values(): self._apply_symbol(cv)

    # ------------ hover / click readout ------------
    def on_mouse_moved(self, pos):
        if self.x_sec is None or self.x_ns is None: return
        if not self.plot.sceneBoundingRect().contains(pos): return
        x = self.plot.plotItem.vb.mapSceneToView(pos).x()
        idx = int(np.abs(self.x_sec - x).argmin())
        if idx < 0 or idx >= len(self.x_sec): return
        self.vline.setPos(self.x_sec[idx])
        t = pd.Timestamp(self.x_ns[idx], tz=KST, unit='ns')
        header = t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " KST"
        active_list = [c for c, a in self.active_for.items() if a]
        parts = []; max_show = 5
        for c in active_list[:max_show]:
            y = self.Y_raw[c]; v = y[idx] if 0 <= idx < len(y) else np.nan
            s = "nan" if (v is None or not np.isfinite(v)) else f"{v:.6g}"
            u = unit_from_name(c); parts.append(f"{c}: {s}{(' '+u) if u else ''}")
        more = "" if len(active_list) <= max_show else f" (+{len(active_list)-max_show} more)"
        self.status.showMessage(f"{header} | " + "  |  ".join(parts) + more)

    def on_plot_clicked(self, evt):
        if self.x_sec is None or self.x_ns is None: return
        if not evt or evt.button() != QtCore.Qt.MouseButton.LeftButton: return
        pos = evt.scenePos() if hasattr(evt, "scenePos") else evt.scenePosition()
        if not self.plot.sceneBoundingRect().contains(pos): return
        x = self.plot.plotItem.vb.mapSceneToView(pos).x()
        idx = int(np.abs(self.x_sec - x).argmin())
        if idx < 0 or idx >= len(self.x_sec): return
        self.vline.setPos(self.x_sec[idx])
        t = pd.Timestamp(self.x_ns[idx], tz=KST, unit='ns')
        header = t.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " KST"
        active_list = sorted([c for c, a in self.active_for.items() if a])
        lines = [header, ""]
        for col in active_list:
            y = self.Y_raw[col]; v = y[idx] if 0 <= idx < len(y) else np.nan
            s = "nan" if (v is None or not np.isfinite(v)) else f"{v:.6g}"
            u = unit_from_name(col)
            lines.append(f"{col:<22}: {s}{(' '+u) if u else ''}")
        if not active_list: lines.append("(no active series)")
        self.info.setPlainText("\n".join(lines))

        # highlight mode: two clicks
        if self.highlight_mode:
            clicked_ns = int(self.x_ns[idx])
            if self.highlight_first_ns is None:
                self.highlight_first_ns = clicked_ns
                self.status.showMessage("Highlight: first point set. Click second point.")
            else:
                s_ns = min(self.highlight_first_ns, clicked_ns)
                e_ns = max(self.highlight_first_ns, clicked_ns)
                text, ok = QtWidgets.QInputDialog.getText(self, "Highlight label", "Label:")
                if ok and text:
                    reg = pg.LinearRegionItem(values=[s_ns/1e9, e_ns/1e9], orientation=pg.LinearRegionItem.Vertical)
                    reg.setZValue(-5); reg.setBrush(pg.mkBrush(255, 215, 0, 40)); reg.setMovable(False)
                    self.plot.addItem(reg)
                    self.highlight_regions.append({'reg': reg, 'text': text})
                self.highlight_first_ns = None
                self.btn_highlight.setChecked(False); self.highlight_mode = False
                self.btn_highlight.setText("Highlight: OFF")
                self.status.showMessage("Highlight added.")

    # ------------ diagnostics ------------
    def _dump_diagnostics(self, include_original_range=False):
        lines = []
        pts = 0 if self.x_sec is None else len(self.x_sec)
        lines.append(f"points={pts}, time_col={self.time_col}\n")
        if not self.series_cols:
            lines.append("(no numeric series)")
        else:
            order = [c for c in self.series_cols if self.active_for.get(c, False)] + \
                    [c for c in self.series_cols if not self.active_for.get(c, False)]
            for c in order:
                y = self.Y_raw[c]; fin = np.isfinite(y); nonzero = np.abs(y[fin]) > 0
                if fin.any():
                    yfin = y[fin]
                    base = f"{c:<22} active={'Y' if self.active_for.get(c, False) else 'N'}  finite={fin.sum():>6}  nonzero={nonzero.sum():>6}  min={np.nanmin(yfin):.6g}  max={np.nanmax(yfin):.6g}"
                    if include_original_range: base += f"  (orig range: {np.nanmin(yfin):.6g} .. {np.nanmax(yfin):.6g})"
                    lines.append(base)
                else:
                    lines.append(f"{c:<22} active={'Y' if self.active_for.get(c, False) else 'N'}  finite=0      nonzero=0      min=nan      max=nan")
        self.info.setPlainText("\n".join(lines))

    # ------------ export ------------
    def export_visible_csv(self):
        if self.x_sec is None or len(self.x_sec)==0: return
        xr, _ = self.plot.getPlotItem().vb.viewRange()
        xmin, xmax = xr
        mask = (self.x_sec >= xmin) & (self.x_sec <= xmax)
        if not mask.any():
            QtWidgets.QMessageBox.information(self, "Export CSV", "No points in current visible X range."); return
        active_cols = [c for c, a in self.active_for.items() if a]
        if not active_cols:
            QtWidgets.QMessageBox.information(self, "Export CSV", "No active series selected."); return
        ts = pd.to_datetime((self.x_sec[mask] * 1e9).astype("int64"), utc=True).tz_convert(KST)
        data = {"Timestamp (KST)": ts}
        for c in active_cols: data[c] = self.Y_raw[c][mask]
        out = pd.DataFrame(data)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save CSV", "dash_visible.csv", "CSV Files (*.csv)")
        if not path: return
        try: out.to_csv(path, index=False); self.status.showMessage(f"Exported CSV: {path}")
        except Exception as e: QtWidgets.QMessageBox.critical(self, "Export CSV Error", str(e))

    def export_plot_png(self):
        try:
            from pyqtgraph.exporters import ImageExporter
        except Exception:
            QtWidgets.QMessageBox.critical(self, "Export PNG Error", "pyqtgraph.exporters not available."); return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save PNG", "dash_plot.png", "PNG Files (*.png)")
        if not path: return
        try:
            exp = ImageExporter(self.plot.plotItem)
            exp.parameters()['width'] = int(self.plot.width())
            exp.export(path)
            self.status.showMessage(f"Exported PNG: {path}")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export PNG Error", str(e))

    # ------------ Copy to clipboard ------------
    def copy_plot_to_clipboard(self):
        pix = self.plot.grab()
        QtGui.QGuiApplication.clipboard().setPixmap(pix)
        self.status.showMessage("Plot image copied to clipboard.")

    def copy_info_to_clipboard(self):
        QtGui.QGuiApplication.clipboard().setText(self.info.toPlainText() or "")
        self.status.showMessage("Info text copied to clipboard.")

    # ------------ Jump-to-Range (patched) ------------
    def _enable_jump_controls(self, min_ns: int, max_ns: int):
        tmin = pd.Timestamp(min_ns, unit='ns', tz=KST).to_pydatetime().replace(tzinfo=None)
        tmax = pd.Timestamp(max_ns, unit='ns', tz=KST).to_pydatetime().replace(tzinfo=None)
        self.dt_start.setDateTime(QtCore.QDateTime(tmin))
        self.dt_end.setDateTime(QtCore.QDateTime(tmax))
        self.dt_start.setEnabled(True); self.dt_end.setEnabled(True); self.btn_jump.setEnabled(True)
        # 초기 전체 범위 보이기
        self.plot.setXRange(min_ns/1e9, max_ns/1e9, padding=0.02)

    def go_to_range(self):
        if self.x_sec is None or self.x_ns is None: return
        s_qt = self.dt_start.dateTime(); e_qt = self.dt_end.dateTime()
        s_dt = _qdatetime_to_py(s_qt);  e_dt = _qdatetime_to_py(e_qt)
        if s_dt >= e_dt:
            QtWidgets.QMessageBox.warning(self, "Range Error", "Start must be earlier than End.")
            return
        s_sec = pd.Timestamp(s_dt).tz_localize(KST).value / 1e9
        e_sec = pd.Timestamp(e_dt).tz_localize(KST).value / 1e9
        xmin = float(np.nanmin(self.x_sec)); xmax = float(np.nanmax(self.x_sec))
        s_sec = float(np.clip(s_sec, xmin, xmax)); e_sec = float(np.clip(e_sec, xmin, xmax))
        if e_sec <= s_sec: e_sec = min(xmax, s_sec + 1.0)
        self.plot.setXRange(s_sec, e_sec, padding=0.02)

    def on_time_col_changed(self, new_col):
        self.time_col = new_col
        self.status.showMessage(f"Time column set to: {new_col} (press Load to apply)")

    # ------------ Bookmarks ------------
    def add_bookmark_dialog(self):
        if self.x_sec is None: return
        xr, _ = self.plot.getPlotItem().vb.viewRange()
        xmid = 0.5*(xr[0]+xr[1])
        idx = int(np.abs(self.x_sec - xmid).argmin())
        x_ns = int(self.x_ns[idx])
        t = pd.Timestamp(x_ns, tz=KST, unit='ns').strftime("%Y-%m-%d %H:%M:%S")
        label, ok = QtWidgets.QInputDialog.getText(self, "Add Bookmark", f"Label (default {t}):")
        if not ok: return
        if not label: label = t
        self.bookmarks.append((x_ns, label))
        self.list_bm.addItem(label)

    def jump_bookmark(self):
        it = self.list_bm.currentItem()
        if not it: return
        idx = self.list_bm.row(it)
        if idx < 0 or idx >= len(self.bookmarks): return
        x_ns, _ = self.bookmarks[idx]
        self._jump_to_ns(x_ns)

    def del_bookmark(self):
        idx = self.list_bm.currentRow()
        if idx < 0: return
        self.list_bm.takeItem(idx)
        if 0 <= idx < len(self.bookmarks): self.bookmarks.pop(idx)

    def _jump_to_ns(self, x_ns:int):
        x_sec = x_ns/1e9
        self.plot.setXRange(x_sec-5, x_sec+5, padding=0.02)
        self.vline.setPos(x_sec)

    # ------------ Highlight / Threshold / Event ------------
    def toggle_highlight_mode(self):
        self.highlight_mode = self.btn_highlight.isChecked()
        self.highlight_first_ns = None
        self.btn_highlight.setText("Highlight: ON" if self.highlight_mode else "Highlight: OFF")
        self.status.showMessage("Highlight mode ON: click two points to mark region." if self.highlight_mode else "Highlight mode OFF")

    def add_threshold_line(self, col:str, value:float):
        line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen(200,0,0,120))
        self.plot.addItem(line, ignoreBounds=True)
        txt = pg.TextItem(html=f"<span style='color:#a00'>TH {col}: {value:g}</span>", anchor=(0,1))
        self.plot.addItem(txt, ignoreBounds=True)
        xr, yr = self.plot.getPlotItem().vb.viewRange()
        line.setPos(value); txt.setPos(xr[0], value)
        self.thresholds.setdefault(col, []).append({'op':'=', 'value': value, 'line': line, 'label': txt})

    def add_event_at_cursor(self):
        if self.x_sec is None: return
        x = self.vline.value() if hasattr(self.vline, 'value') else None
        if x is None:
            xr, _ = self.plot.getPlotItem().vb.viewRange(); x = 0.5*(xr[0]+xr[1])
        idx = int(np.abs(self.x_sec - x).argmin())
        x_ns = int(self.x_ns[idx])
        text, ok = QtWidgets.QInputDialog.getText(self, "Add Event / Note", "Label:")
        if not ok or not text: return
        self._add_event_line(x_ns, text)

    def _add_event_line(self, x_ns:int, text:str, color=(0,120,200)):
        x_sec = x_ns/1e9
        line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen(color, width=1.5))
        self.plot.addItem(line, ignoreBounds=True); line.setPos(x_sec)
        lbl = pg.TextItem(text=text, anchor=(0,1))
        self.plot.addItem(lbl, ignoreBounds=True); lbl.setPos(x_sec, self.plot.getPlotItem().vb.viewRange()[1][1])
        self.event_items.append({'x_ns':x_ns, 'line': line, 'label': lbl, 'series': None, 'text': text})
        t = pd.Timestamp(x_ns, tz=KST, unit='ns').strftime("%Y-%m-%d %H:%M:%S")
        self.list_events.addItem(f"{t} | {text}")

    # ------------ Conditions ------------
    def run_event_finder(self):
        if self.x_sec is None or not self.find_rules: return
        for col, rules in self.find_rules.items():
            y = self.Y_raw.get(col); 
            if y is None or y.size < 2: continue
            valid = np.isfinite(y)
            xs = self.x_ns[valid]; yy = y[valid]
            hits_idx = np.zeros_like(yy, dtype=bool)
            if 'gt' in rules: hits_idx |= (yy > float(rules['gt']))
            if 'lt' in rules: hits_idx |= (yy < float(rules['lt']))
            if 'deltapct' in rules:
                dy = np.empty_like(yy); dy[:] = np.nan
                dy[1:] = np.abs((yy[1:] - yy[:-1]) / np.where(yy[:-1]==0, np.nan, yy[:-1])) * 100.0
                hits_idx |= (dy >= float(rules['deltapct']))
            where = np.where(hits_idx)[0]
            for i in where:
                x_ns = int(xs[i])
                label = []
                if 'gt' in rules and yy[i] > float(rules['gt']): label.append(f"{col}>")
                if 'lt' in rules and yy[i] < float(rules['lt']): label.append(f"{col}<")
                if 'deltapct' in rules and i>0:
                    pct = abs((yy[i]-yy[i-1])/(yy[i-1] if yy[i-1]!=0 else np.nan))*100.0
                    if np.isfinite(pct) and pct >= float(rules['deltapct']): label.append(f"{col} Δ{pct:.1f}%")
                text = " / ".join(label) if label else col
                self._add_event_line(x_ns, text)
                tt = pd.Timestamp(x_ns, tz=KST, unit='ns').strftime("%Y-%m-%d %H:%M:%S")
                self.list_events.addItem(f"{tt} | {text}")

    def jump_event_item(self, it: QtWidgets.QListWidgetItem):
        if it is None: return
        s = it.text().split("|",1)[0].strip()
        try:
            x_ns = int(pd.Timestamp(s, tz=KST).value)
            self._jump_to_ns(x_ns)
        except Exception:
            pass

    # ------------ Compare overlay ------------
    def toggle_compare_mode(self):
        self.compare_mode = self.btn_compare.isChecked()
        self.btn_open_ref.setEnabled(self.compare_mode)
        self.btn_compare.setText("Compare: ON" if self.compare_mode else "Compare: OFF")
        if not self.compare_mode:
            for cv in self.curves_ref.values():
                try: self.plot.removeItem(cv)
                except Exception: pass
            self.curves_ref.clear()
            self._refresh_legend()

    def open_compare_file(self):
        if not self.compare_mode: return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open Ref Data File", "", "Data Files (*.csv *.tsv *.dat);;All Files (*)")
        if not path: return
        try:
            delim = sniff_delimiter_quick(path)
            if HAS_POLARS:
                df = pl.read_csv(path, infer_schema_length=10000, has_header=True) if delim is None else \
                     pl.read_csv(path, infer_schema_length=10000, separator=delim, has_header=True)
                tcol = next((c for c in TIME_COL_CANDIDATES if c in df.columns), df.columns[0])
                ts_expr = pl.col(tcol).str.strptime(pl.Datetime, strict=False, exact=False)
                df = df.with_columns([ts_expr.alias("_ts_").dt.replace_time_zone("UTC").dt.convert_time_zone("Asia/Seoul")]) \
                       .drop_nulls(["_ts_"]).sort("_ts_")
                num_cols = [c for c, dt in zip(df.columns, df.dtypes) if c not in (tcol, "_ts_") and is_numeric_polars_dtype(dt)]
                x_ns  = df["_ts_"].dt.timestamp("ns").to_numpy().astype("int64", copy=False)
                x_sec = x_ns.astype("float64") / 1e9
                Y_raw = {col: df[col].to_numpy().astype("float64", copy=False) for col in num_cols}
            else:
                df = pd.read_csv(path, sep=delim) if delim is not None else pd.read_csv(path, sep=None, engine="python")
                tcol = next((c for c in TIME_COL_CANDIDATES if c in df.columns), df.columns[0])
                ts = pd.to_datetime(df[tcol], errors="coerce").dt.tz_localize("UTC").dt.tz_convert(KST)
                df = df.assign(_ts_=ts).dropna(subset=["_ts_"]).sort_values("_ts_")
                num_cols = [c for c in df.columns if c not in (tcol, "_ts_") and pd.api.types.is_numeric_dtype(df[c])]
                x_ns  = df["_ts_"].view("int64").to_numpy()
                x_sec = x_ns.astype("float64") / 1e9
                Y_raw = {col: pd.to_numeric(df[col], errors='coerce').to_numpy(dtype="float64", copy=False) for col in num_cols}
            self.compare_data = {'x_ns': x_ns, 'x_sec': x_sec, 'Y_raw': Y_raw, 'series_cols': list(Y_raw.keys())}
            self.plot_compare_overlay()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Compare Error", str(e))

    def plot_compare_overlay(self):
        if not self.compare_data: return
        common = [c for c in self.series_cols if c in self.compare_data['series_cols']]
        for c in common:
            cv = self.plot.plot(self.compare_data['x_sec'], self.compare_data['Y_raw'][c],
                                name=f"{c} (ref)", pen=pg.mkPen((60,60,60,140), width=1.5, style=QtCore.Qt.PenStyle.DotLine))
            self.curves_ref[c] = cv
        self._refresh_legend()

    # ------------ Help ------------
    def show_help(self):
        QtWidgets.QMessageBox.information(
            self, "DASH — Shortcuts",
            "L: Linear scale\n"
            "G: Log scale\n"
            "N: Normalize (0..1)\n"
            "A: All On (activate all series)\n"
            "D: All Off (deactivate all series)\n"
            "F: Fit view (like AutoRange)\n"
            "E: Add Event/Note at cursor\n"
            "B: Add Bookmark (current center)\n"
            "?: Show this help\n\n"
            "Right-click a series → Conditions / Threshold / Downsampling / Color\n"
            "Top button toggles global Downsampling.\n"
            "Click a series to toggle Active/Inactive (no checkboxes).\n"
            "Highlight: toggle button ON, click two points to mark region.\n"
            "Compare: toggle ON, load Ref file to overlay matching series."
        )

def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    app = QtWidgets.QApplication(sys.argv)
    win = DASH(); win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
