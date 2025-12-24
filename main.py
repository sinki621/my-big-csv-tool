import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from dateutil import parser
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QFileDialog, QMessageBox, QLabel, 
                             QListWidget, QListWidgetItem, QAbstractItemView)
from PyQt5.QtCore import Qt

class DateAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values if value > 0]

class BigDataChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.df = None
        self.x_timestamps = None
        self.plot_items = {} # 그려진 라인 객체들을 저장

    def initUI(self):
        self.setWindowTitle('Advanced Multi-Column Visualizer')
        
        # 메인 레이아웃 (좌우 배치)
        main_layout = QHBoxLayout()
        
        # --- 왼쪽 제어판 (리스트 및 버튼) ---
        side_layout = QVBoxLayout()
        
        self.btn = QPushButton('CSV 불러오기', self)
        self.btn.setFixedHeight(40)
        self.btn.clicked.connect(self.loadCSV)
        side_layout.addWidget(self.btn)

        side_layout.addWidget(QLabel("표시할 데이터 선택:"))
        self.columnList = QListWidget()
        self.columnList.setSelectionMode(QAbstractItemView.NoSelection)
        self.columnList.itemChanged.connect(self.updatePlots)
        side_layout.addWidget(self.columnList)
        
        side_widget = QWidget()
        side_widget.setLayout(side_layout)
        side_widget.setFixedWidth(200)
        
        # --- 오른쪽 그래프 영역 ---
        graph_layout = QVBoxLayout()
        self.infoLabel = QLabel("CSV 파일을 불러와주세요.")
        graph_layout.addWidget(self.infoLabel)

        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.addLegend()
        graph_layout.addWidget(self.graphWidget)

        # 십자선 설정
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen='k')
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen='k')
        self.graphWidget.addItem(self.vLine, ignoreBounds=True)
        self.graphWidget.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.graphWidget.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)

        # 전체 레이아웃 합치기
        main_layout.addWidget(side_widget)
        main_layout.addLayout(graph_layout)
        
        self.setLayout(main_layout)
        self.resize(1200, 800)

    def parse_dates_custom(self, series):
        try:
            return series.cast(pl.Datetime).cast(pl.Int64) / 10**6
        except:
            sample = str(series[0])
            try:
                parsed_sample = parser.parse(sample)
                return series.map_elements(lambda x: parser.parse(str(x)).timestamp(), return_dtype=pl.Float64)
            except:
                return pl.Series(np.arange(len(series)))

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                self.df = pl.read_csv(fname, try_parse_dates=True)
                self.graphWidget.clear()
                self.plot_items = {}
                self.columnList.clear()
                
                # X축 처리
                x_col = self.df.columns[0]
                self.x_timestamps = self.parse_dates_custom(self.df.get_column(x_col)).to_numpy()
                
                # 십자선 재등록
                self.graphWidget.addItem(self.vLine)
                self.graphWidget.addItem(self.hLine)

                # Y축 리스트업 (체크박스 생성)
                colors = ['b', 'r', 'g', 'c', 'm', 'y']
                for i, col_name in enumerate(self.df.columns[1:]):
                    item = QListWidgetItem(col_name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked) # 기본값: 체크됨
                    self.columnList.addItem(item)
                    
                    # 미리 그래프를 생성하되 보이게 설정
                    y_data = self.df.get_column(col_name).to_numpy()
                    plot = self.graphWidget.plot(self.x_timestamps, y_data, 
                                                pen=pg.mkPen(color=colors[i % len(colors)], width=1), 
                                                name=col_name)
                    self.plot_items[col_name] = plot

                self.graphWidget.autoRange()
                self.infoLabel.setText(f"완료: {len(self.df)}행 로드")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"파일 읽기 실패: {str(e)}")

    def updatePlots(self, item):
        """체크박스 상태에 따라 그래프를 보이거나 숨김"""
        col_name = item.text()
        if col_name in self.plot_items:
            if item.checkState() == Qt.Checked:
                self.plot_items[col_name].show()
            else:
                self.plot_items[col_name].hide()

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.x_timestamps, mousePoint.x())
            
            if 0 <= index < len(self.df):
                actual_x = self.x_timestamps[index]
                date_str = datetime.fromtimestamp(actual_x).strftime('%Y-%m-%d %H:%M:%S')
                val_str = f"[{date_str}]"
                
                # 체크된 열의 데이터만 상단 라벨에 표시
                for i in range(self.columnList.count()):
                    item = self.columnList.item(i)
                    if item.checkState() == Qt.Checked:
                        col = item.text()
                        val_str += f" | {col}: {self.df[index, col]}"
                
                self.infoLabel.setText(val_str)
                self.vLine.setPos(actual_x)
                self.hLine.setPos(mousePoint.y())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BigDataChartApp()
    ex.show()
    sys.exit(app.exec_())
