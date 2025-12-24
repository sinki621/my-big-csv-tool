import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QLabel, 
                             QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore import Qt

# 성능 최적화 설정
pg.setConfigOptions(antialias=False, useOpenGL=True)

class DateAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values if value > 0]

class UltimateChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.df = None
        self.x_timestamps = None
        self.plot_items = {}

    def initUI(self):
        self.setWindowTitle('1M+ Ultra Visualizer Pro')
        main_layout = QHBoxLayout()
        
        # --- 왼쪽 제어판 ---
        side_layout = QVBoxLayout()
        
        self.btn = QPushButton('CSV 파일 불러오기', self)
        self.btn.setFixedHeight(45)
        self.btn.setStyleSheet("background-color: #e1e1e1; font-weight: bold;")
        self.btn.clicked.connect(self.loadCSV)
        side_layout.addWidget(self.btn)

        # 전체 선택/해제 버튼
        btn_layout = QHBoxLayout()
        self.selectAllBtn = QPushButton('전체 선택')
        self.selectNoneBtn = QPushButton('전체 해제')
        self.selectAllBtn.clicked.connect(lambda: self.setAllCheckState(Qt.Checked))
        self.selectNoneBtn.clicked.connect(lambda: self.setAllCheckState(Qt.Unchecked))
        btn_layout.addWidget(self.selectAllBtn)
        btn_layout.addWidget(self.selectNoneBtn)
        side_layout.addLayout(btn_layout)

        side_layout.addWidget(QLabel("Y축 데이터 선택:"))
        self.columnList = QListWidget()
        self.columnList.setSelectionMode(QAbstractItemView.NoSelection)
        self.columnList.itemChanged.connect(self.updatePlots)
        side_layout.addWidget(self.columnList)
        
        side_widget = QWidget(); side_widget.setLayout(side_layout); side_widget.setFixedWidth(220)
        
        # --- 오른쪽 그래프 영역 ---
        graph_layout = QVBoxLayout()
        self.infoLabel = QLabel("마우스 휠로 확대/축소, 마우스 우클릭 드래그로 축별 이동이 가능합니다.")
        graph_layout.addWidget(self.infoLabel)

        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        
        # 확대/축소 및 성능 설정
        self.graphWidget.setMouseEnabled(x=True, y=True) # 휠 확대/축소 활성화
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
        self.resize(1300, 850)

    def setAllCheckState(self, state):
        """리스트의 모든 체크박스 상태를 변경"""
        self.columnList.blockSignals(True) # 대량 변경 시 이벤트 일시 정지 (렉 방지)
        for i in range(self.columnList.count()):
            item = self.columnList.item(i)
            item.setCheckState(state)
            col_name = item.text()
            if col_name in self.plot_items:
                self.plot_items[col_name].setVisible(state == Qt.Checked)
        self.columnList.blockSignals(False)
        self.graphWidget.autoRange() # 전체 선택/해제 후 화면 맞춤

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                self.df = pl.read_csv(fname, try_parse_dates=True)
                self.graphWidget.clear()
                self.plot_items = {}
                self.columnList.clear()
                self.graphWidget.addItem(self.vLine)

                x_col = self.df.columns[0]
                self.x_timestamps = (self.df[x_col].cast(pl.Datetime).cast(pl.Int64) / 10**6).to_numpy()
                
                colors = ['b', 'r', 'g', 'c', 'm', 'y']
                for i, col_name in enumerate(self.df.columns[1:]):
                    item = QListWidgetItem(col_name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked)
                    self.columnList.addItem(item)
                    
                    y_data = self.df[col_name].to_numpy()
                    plot = pg.PlotDataItem(self.x_timestamps, y_data, 
                                           pen=pg.mkPen(color=colors[i % 6], width=1.2), 
                                           name=col_name, skipFiniteCheck=True)
                    self.graphWidget.addItem(plot)
                    self.plot_items[col_name] = plot

                # 불러오기 직후 자동으로 전체 데이터에 맞게 스케일 조정
                self.graphWidget.autoRange()
                self.infoLabel.setText(f"데이터 로드 완료: {len(self.df):,} 행")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"로드 실패: {str(e)}")

    def updatePlots(self, item):
        col_name = item.text()
        if col_name in self.plot_items:
            self.plot_items[col_name].setVisible(item.checkState() == Qt.Checked)
            # 체크 상태 변경 시 화면 스케일 자동 재조정 (선택 사항)
            # self.graphWidget.autoRange() 

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.x_timestamps, mousePoint.x())
            
            if 0 <= index < len(self.df):
                date_str = datetime.fromtimestamp(self.x_timestamps[index]).strftime('%Y-%m-%d %H:%M:%S')
                val_str = f"[{date_str}]"
                for i in range(self.columnList.count()):
                    item = self.columnList.item(i)
                    if item.checkState() == Qt.Checked:
                        col = item.text()
                        val_str += f" | {col}: {self.df[index, col]}"
                self.infoLabel.setText(val_str)
                self.vLine.setPos(mousePoint.x())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = UltimateChartApp()
    ex.show()
    sys.exit(app.exec_())
