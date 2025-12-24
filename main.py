import sys
import polars as pl
import pyqtgraph as pg
import numpy as np
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QFileDialog, QMessageBox

class BigDataChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('Multi-Column Time Series Visualizer')
        layout = QVBoxLayout()

        self.btn = QPushButton('대용량 CSV 파일 불러오기', self)
        self.btn.setFixedHeight(50)
        self.btn.clicked.connect(self.loadCSV)
        layout.addWidget(self.btn)

        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.addLegend() # 범례 추가
        layout.addWidget(self.graphWidget)

        self.setLayout(layout)
        self.resize(1000, 700)

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                # 1. Polars로 데이터 로드
                df = pl.read_csv(fname, infer_schema_length=10000)
                self.graphWidget.clear()

                # 2. X축 처리 (첫 번째 열이 날짜인 경우 숫자로 변환)
                x_col = df.columns[0]
                # 날짜 문자열을 시계열 데이터로 파싱 시도
                try:
                    x_data = df.get_column(x_col).cast(pl.Datetime).cast(pl.Int64).to_numpy() / 10**6 # ms 단위
                except:
                    # 날짜 형식이 아니면 단순히 행 번호로 처리
                    x_data = np.arange(len(df))

                # 3. Y축 처리 (2번째 열부터 마지막 열까지 모두 그리기)
                colors = ['b', 'r', 'g', 'c', 'm', 'y', 'k'] # 선 색상 목록
                for i, col_name in enumerate(df.columns[1:]):
                    y_data = df.get_column(col_name).to_numpy()
                    color = colors[i % len(colors)]
                    self.graphWidget.plot(x_data, y_data, pen=pg.mkPen(color=color, width=1.5), name=col_name)

                self.graphWidget.autoRange()
                
            except Exception as e:
                QMessageBox.critical(self, "에러 발생", f"오류 메시지:\n{str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BigDataChartApp()
    ex.show()
    sys.exit(app.exec_())
