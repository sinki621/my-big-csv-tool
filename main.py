import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from datetime import datetime
from PyQt5.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, QFileDialog, QMessageBox, QLabel
from PyQt5.QtCore import Qt

class DateAxisItem(pg.AxisItem):
    """숫자 데이터를 날짜 형식으로 변환해주는 축 클래스"""
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values]

class BigDataChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.df = None

    def initUI(self):
        self.setWindowTitle('High-Speed Date Chart Visualizer')
        layout = QVBoxLayout()

        self.btn = QPushButton('대용량 CSV 파일 불러오기', self)
        self.btn.setFixedHeight(50)
        self.btn.clicked.connect(self.loadCSV)
        layout.addWidget(self.btn)

        # 마우스 위치 정보를 보여줄 라벨
        self.infoLabel = QLabel("마우스를 그래프 위에 올리면 데이터가 표시됩니다.")
        layout.addWidget(self.infoLabel)

        # 날짜 축 적용된 그래프 위젯
        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.addLegend()
        layout.addWidget(self.graphWidget)

        # 십자선(Crosshair) 설정
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen='k')
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen='k')
        self.graphWidget.addItem(self.vLine, ignoreBounds=True)
        self.graphWidget.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.graphWidget.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)

        self.setLayout(layout)
        self.resize(1200, 800)

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                # 데이터 로드 및 날짜 파싱
                self.df = pl.read_csv(fname, try_parse_dates=True)
                self.graphWidget.clear()
                self.graphWidget.addItem(self.vLine)
                self.graphWidget.addItem(self.hLine)

                x_col = self.df.columns[0]
                # 날짜를 timestamp(초)로 변환
                x_data = self.df.get_column(x_col).cast(pl.Datetime).cast(pl.Int64).to_numpy() / 10**6 

                colors = ['b', 'r', 'g', 'c', 'm']
                for i, col_name in enumerate(self.df.columns[1:]):
                    y_data = self.df.get_column(col_name).to_numpy()
                    self.graphWidget.plot(x_data, y_data, pen=pg.mkPen(color=colors[i % 5], width=1), name=col_name)

                self.graphWidget.autoRange()
            except Exception as e:
                QMessageBox.critical(self, "에러", f"파일 오류: {e}")

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.df.get_column(self.df.columns[0]).cast(pl.Datetime).cast(pl.Int64).to_numpy() / 10**6, mousePoint.x())
            
            if 0 < index < len(self.df):
                date_str = datetime.fromtimestamp(mousePoint.x()).strftime('%Y-%m-%d %H:%M:%S')
                val_str = f"시간: {date_str}"
                for col in self.df.columns[1:]:
                    val_str += f" | {col}: {self.df[index, col]:.2f}"
                
                self.infoLabel.setText(val_str)
                self.vLine.setPos(mousePoint.x())
                self.hLine.setPos(mousePoint.y())

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BigDataChartApp()
    ex.show()
    sys.exit(app.exec_())
