import sys
import polars as pl
import pyqtgraph as pg
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QFileDialog, QMessageBox

class BigDataChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('1M+ Row CSV Visualizer (High Speed)')
        layout = QVBoxLayout()

        # 파일 불러오기 버튼
        self.btn = QPushButton('대용량 CSV 파일 불러오기 (Polars 엔진)', self)
        self.btn.setFixedHeight(50)
        self.btn.clicked.connect(self.loadCSV)
        layout.addWidget(self.btn)

        # 고성능 차트 위젯 (PyQtGraph)
        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground('w')  # 배경 흰색
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.addLegend()
        layout.addWidget(self.graphWidget)

        self.setLayout(layout)
        self.resize(1000, 700)

    def loadCSV(self):
        fname = QFileDialog.getOpenFileName(self, 'Open file', './', "CSV files (*.csv)")[0]
        if fname:
            try:
                # 1. Polars로 초고속 읽기
                df = pl.read_csv(fname)
                
                # 차트 초기화
                self.graphWidget.clear()
                
                # 2. 데이터 렌더링 (첫 번째 열을 X, 두 번째 열을 Y로 가정)
                # 데이터가 너무 많을 경우를 대비해 numpy array로 변환
                x_data = df.to_pandas().iloc[:, 0].values # X축
                y_data = df.to_pandas().iloc[:, 1].values # Y축

                # 3. PyQtGraph로 그리기 (GPU 가속 활용)
                self.graphWidget.plot(x_data, y_data, pen=pg.mkPen(color='b', width=1), name="Data")
                
            except Exception as e:
                QMessageBox.about(self, "Error", f"실패: {str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BigDataChartApp()
    ex.show()
    sys.exit(app.exec_())
