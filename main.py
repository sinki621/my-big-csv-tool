import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QLabel, 
                             QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore import Qt

# 성능 및 그래픽 설정
pg.setConfigOptions(antialias=False, useOpenGL=True)

class DateAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values if value > 0]

class ProfessionalChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.df = None
        self.x_timestamps = None
        self.plot_items = {}

    def initUI(self):
        self.setWindowTitle('Ultra CSV Analyzer Pro')
        main_layout = QHBoxLayout()
        
        # --- 왼쪽 제어판 ---
        side_layout = QVBoxLayout()
        
        self.btn = QPushButton('CSV 파일 불러오기', self)
        self.btn.setFixedHeight(45)
        self.btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; border-radius: 5px;")
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

        side_layout.addWidget(QLabel("Y축 데이터 항목:"))
        self.columnList = QListWidget()
        self.columnList.setSelectionMode(QAbstractItemView.NoSelection)
        self.columnList.itemChanged.connect(self.updatePlots)
        side_layout.addWidget(self.columnList)
        
        side_widget = QWidget(); side_widget.setLayout(side_layout); side_widget.setFixedWidth(240)
        
        # --- 오른쪽 그래프 영역 ---
        graph_layout = QVBoxLayout()
        self.infoLabel = QLabel("데이터를 로드한 후 항목을 선택하세요.")
        self.infoLabel.setStyleSheet("font-weight: bold; color: #333;")
        graph_layout.addWidget(self.infoLabel)

        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        
        # 범례 설정 (왼쪽 상단 고정)
        self.legend = self.graphWidget.addLegend(offset=(10, 10))
        
        # 성능 및 확대/축소 설정
        self.graphWidget.setClipToView(True)
        self.graphWidget.setDownsampling(mode='peak')
        graph_layout.addWidget(self.graphWidget)

        # 십자선
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen='k')
        self.graphWidget.addItem(self.vLine, ignoreBounds=True)

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
            col_name = item.text()
            if col_name in self.plot_items:
                if state == Qt.Checked:
                    self.plot_items[col_name].show()
                else:
                    self.plot_items[col_name].hide()
        self.columnList.blockSignals(False)
        self.graphWidget.autoRange()

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                # 데이터 로드
                self.df = pl.read_csv(fname, try_parse_dates=True)
                self.graphWidget.clear()
                self.legend.clear()
                self.plot_items = {}
                self.columnList.clear()
                self.graphWidget.addItem(self.vLine)

                # X축 처리
                x_col = self.df.columns[0]
                self.x_timestamps = (self.df[x_col].cast(pl.Datetime).cast(pl.Int64) / 10**6).to_numpy()
                
                # 가용 범위 제한 설정 (데이터의 최소/최대 범위 밖으로 이동 불가)
                x_min, x_max = self.x_timestamps.min(), self.x_timestamps.max()
                self.graphWidget.setLimits(xMin=x_min, xMax=x_max)

                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b']
                for i, col_name in enumerate(self.df.columns[1:]):
                    item = QListWidgetItem(col_name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked) # 초기 상태: 해제
                    self.columnList.addItem(item)
                    
                    y_data = self.df[col_name].to_numpy()
                    plot = pg.PlotDataItem(self.x_timestamps, y_data, 
                                           pen=pg.mkPen(color=colors[i % len(colors)], width=1.5), 
                                           name=col_name, skipFiniteCheck=True)
                    plot.hide() # 초기 상태: 숨김
                    self.graphWidget.addItem(plot)
                    self.plot_items[col_name] = plot

                self.graphWidget.autoRange()
                self.infoLabel.setText(f"파일 로드 완료: {len(self.df):,} 행")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"로드 실패: {str(e)}")

    def updatePlots(self, item):
        col_name = item.text()
        if col_name in self.plot_items:
            if item.checkState() == Qt.Checked:
                self.plot_items[col_name].show()
            else:
                self.plot_items[col_name].hide()
            
            # 항목이 바뀔 때마다 자동으로 전체 화면 맞춤 (AutoScale)
            self.graphWidget.autoRange()

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.x_timestamps, mousePoint.x())
            
            if 0 <= index < len(self.df):
                date_str = datetime.fromtimestamp(self.x_timestamps[index]).strftime('%Y-%m-%d %H:%M:%S')
                val_str = f"[{date_str}]"
                active_count = 0
                for i in range(self.columnList.count()):
                    item = self.columnList.item(i)
                    if item.checkState() == Qt.Checked:
                        col = item.text()
                        val_str += f" | {col}: {self.df[index, col]}"
                        active_count += 1
                
                if active_count > 0:
                    self.infoLabel.setText(val_str)
                    self.vLine.setPos(mousePoint.x())
                else:
                    self.infoLabel.setText("표시할 데이터를 선택해주세요.")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = ProfessionalChartApp()
    ex.show()
    sys.exit(app.exec_())
