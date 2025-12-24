import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QLabel, 
                             QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore import Qt, QPointF

# 성능 및 인터랙티브 설정
pg.setConfigOptions(antialias=False, useOpenGL=True, leftButtonSelection=True)

class DateAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values if value > 0]

class AnalysisChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.df = None
        self.x_timestamps = None
        self.plot_items = {}

    def initUI(self):
        self.setWindowTitle('Professional CSV Data Analyzer')
        main_layout = QHBoxLayout()
        
        # --- 왼쪽 제어판 ---
        side_layout = QVBoxLayout()
        
        self.btn = QPushButton('CSV 파일 불러오기', self)
        self.btn.setFixedHeight(45)
        self.btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        self.btn.clicked.connect(self.loadCSV)
        side_layout.addWidget(self.btn)

        btn_layout = QHBoxLayout()
        self.selectAllBtn = QPushButton('전체 선택')
        self.selectNoneBtn = QPushButton('전체 해제')
        self.selectAllBtn.clicked.connect(lambda: self.setAllCheckState(Qt.Checked))
        self.selectNoneBtn.clicked.connect(lambda: self.setAllCheckState(Qt.Unchecked))
        btn_layout.addWidget(self.selectAllBtn)
        btn_layout.addWidget(self.selectNoneBtn)
        side_layout.addLayout(btn_layout)

        side_layout.addWidget(QLabel("데이터 항목 (Y축):"))
        self.columnList = QListWidget()
        self.columnList.itemChanged.connect(self.updatePlots)
        side_layout.addWidget(self.columnList)

        # 도움말 추가
        help_text = "💡 도움말\n- 왼쪽 드래그: 영역 확대\n- 오른쪽 클릭: 전체 보기\n- 마우스 휠: 확대/축소"
        side_layout.addWidget(QLabel(help_text))
        
        side_widget = QWidget(); side_widget.setLayout(side_layout); side_widget.setFixedWidth(240)
        
        # --- 오른쪽 그래프 영역 ---
        graph_layout = QVBoxLayout()
        
        # 툴팁 역할을 할 라벨 (그래프 위에 띄움)
        self.tooltip = QLabel("", self)
        self.tooltip.setStyleSheet("""
            background-color: rgba(255, 255, 255, 200); 
            border: 1px solid black; 
            padding: 5px; 
            font-family: Consolas;
        """)
        self.tooltip.hide()

        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        
        # 드래그 확대 기능 활성화 (왼쪽 버튼으로 영역 지정)
        self.graphWidget.setMouseEnabled(x=True, y=True)
        self.graphWidget.getViewBox().setMouseMode(pg.ViewBox.RectMode) 
        
        graph_layout.addWidget(self.graphWidget)

        # 십자선 (포인터 추적용)
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('k', width=1, style=Qt.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('k', width=1, style=Qt.DashLine))
        self.graphWidget.addItem(self.vLine, ignoreBounds=True)
        self.graphWidget.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.graphWidget.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)

        main_layout.addWidget(side_widget)
        main_layout.addLayout(graph_layout)
        self.setLayout(main_layout)
        self.resize(1400, 900)

    def setAllCheckState(self, state):
        self.columnList.blockSignals(True)
        for i in range(self.columnList.count()):
            item = self.columnList.item(i)
            item.setCheckState(state)
            if item.text() in self.plot_items:
                self.plot_items[item.text()].setVisible(state == Qt.Checked)
        self.columnList.blockSignals(False)
        self.graphWidget.autoRange()

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                self.df = pl.read_csv(fname, try_parse_dates=True)
                self.graphWidget.clear()
                self.plot_items = {}
                self.columnList.clear()
                self.graphWidget.addItem(self.vLine)
                self.graphWidget.addItem(self.hLine)

                x_col = self.df.columns[0]
                self.x_timestamps = (self.df[x_col].cast(pl.Datetime).cast(pl.Int64) / 10**6).to_numpy()
                self.graphWidget.setLimits(xMin=self.x_timestamps.min(), xMax=self.x_timestamps.max())

                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
                for i, col_name in enumerate(self.df.columns[1:]):
                    item = QListWidgetItem(col_name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    self.columnList.addItem(item)
                    
                    y_data = self.df[col_name].to_numpy()
                    plot = pg.PlotDataItem(self.x_timestamps, y_data, 
                                           pen=pg.mkPen(color=colors[i % 5], width=1.5), 
                                           name=col_name, skipFiniteCheck=True)
                    plot.hide()
                    self.graphWidget.addItem(plot)
                    self.plot_items[col_name] = plot

                self.graphWidget.autoRange()
            except Exception as e:
                QMessageBox.critical(self, "에러", f"로드 실패: {str(e)}")

    def updatePlots(self, item):
        if item.text() in self.plot_items:
            self.plot_items[item.text()].setVisible(item.checkState() == Qt.Checked)
            self.graphWidget.autoRange()

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.x_timestamps, mousePoint.x())
            
            if 0 <= index < len(self.df):
                date_str = datetime.fromtimestamp(self.x_timestamps[index]).strftime('%Y-%m-%d %H:%M:%S')
                
                # 팝업 툴팁 내용 구성
                tooltip_text = f"📅 {date_str}"
                any_checked = False
                for i in range(self.columnList.count()):
                    item = self.columnList.item(i)
                    if item.checkState() == Qt.Checked:
                        col = item.text()
                        tooltip_text += f"\n📊 {col}: {self.df[index, col]:.4f}"
                        any_checked = True
                
                if any_checked:
                    self.tooltip.setText(tooltip_text)
                    self.tooltip.adjustSize()
                    
                    # 마우스 포인터 근처에 툴팁 배치 (화면 밖으로 나가지 않게 오프셋 부여)
                    global_pos = self.mapFromGlobal(self.graphWidget.mapToGlobal(pos.toPoint()))
                    self.tooltip.move(global_pos.x() + 15, global_pos.y() + 15)
                    self.tooltip.show()
                    
                    self.vLine.setPos(mousePoint.x())
                    self.hLine.setPos(mousePoint.y())
                else:
                    self.tooltip.hide()
        else:
            self.tooltip.hide()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = AnalysisChartApp()
    ex.show()
    sys.exit(app.exec_())
