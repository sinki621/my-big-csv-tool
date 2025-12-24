import sys
import os

# 에러 로그를 확인하기 위한 설정
def exception_hook(exctype, value, traceback):
    print(exctype, value, traceback)
    sys._excepthook(exctype, value, traceback)
    sys.exit(1)

sys.excepthook = exception_hook

try:
    import polars as pl
    import pyqtgraph as pg
    from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QVBoxLayout, QFileDialog, QMessageBox
    from PyQt5.QtCore import Qt
except ImportError as e:
    print(f"필수 라이브러리 로드 실패: {e}")

class BigDataChartApp(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle('1M+ Row CSV Visualizer')
        layout = QVBoxLayout()

        self.btn = QPushButton('대용량 CSV 파일 불러오기', self)
        self.btn.setFixedHeight(50)
        self.btn.clicked.connect(self.loadCSV)
        layout.addWidget(self.btn)

        self.graphWidget = pg.PlotWidget()
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        layout.addWidget(self.graphWidget)

        self.setLayout(layout)
        self.resize(1000, 700)

    def loadCSV(self):
        fname, _ = QFileDialog.getOpenFileName(self, 'Open file', '', "CSV files (*.csv)")
        if fname:
            try:
                # Polars로 읽기 (메모리 효율적 방식)
                df = pl.scan_csv(fname).collect()
                
                self.graphWidget.clear()
                
                # 데이터가 있는지 확인
                if df.width < 2:
                    QMessageBox.warning(self, "경고", "CSV 파일에 최소 2개 이상의 열이 필요합니다.")
                    return

                # 고속 렌더링을 위해 numpy 변환
                x = df.get_column(df.columns[0]).to_numpy()
                y = df.get_column(df.columns[1]).to_numpy()

                self.graphWidget.plot(x, y, pen=pg.mkPen(color='b', width=1))
                self.graphWidget.autoRange()
                
            except Exception as e:
                QMessageBox.critical(self, "에러 발생", f"파일을 읽는 중 오류가 발생했습니다:\n{str(e)}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = BigDataChartApp()
    ex.show()
    sys.exit(app.exec_())
