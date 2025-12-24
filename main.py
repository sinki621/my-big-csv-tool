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
pg.setConfigOptions(antialias=False, useOpenGL=True, leftButtonSelection=True)

class DateAxisItem(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [datetime.fromtimestamp(value).strftime('%Y-%m-%d\n%H:%M:%S') for value in values if value > 0]

class FinalAnalysisApp(QWidget):
    def __init__(self):
        super().__init__()
        self.colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', 
                       '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']
        self.initUI()
        self.df = None
        self.x_timestamps = None
        self.plot_items = {}

    def initUI(self):
        self.setWindowTitle('Ultra CSV Analyzer - Wide View')
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
        
        side_widget = QWidget(); side_widget.setLayout(side_layout); side_widget.setFixedWidth(250)
        
        # --- 오른쪽 그래프 영역 ---
        graph_layout = QVBoxLayout()
        
        # 상단 정보창 (범례 대용: 선택된 항목의 색상을 텍스트로 표시)
        self.infoLabel = QLabel("CSV 파일을 로드해주세요.")
        self.infoLabel.setWordWrap(True)
        self.infoLabel.setStyleSheet("background-color: #f0f0f0; padding: 10px; border: 1px solid #ccc; font-family: 'Malgun Gothic';")
        graph_layout.addWidget(self.infoLabel)

        # 플로팅 툴팁 (마우스 위치 정보)
        self.tooltip = QLabel("", self)
        self.tooltip.setStyleSheet("background-color: rgba(255, 255, 255, 220); border: 1px solid black; padding: 5px;")
        self.tooltip.hide()

        date_axis = DateAxisItem(orientation='bottom')
        self.graphWidget = pg.PlotWidget(axisItems={'bottom': date_axis})
        self.graphWidget.setBackground('w')
        self.graphWidget.showGrid(x=True, y=True)
        self.graphWidget.getViewBox().setMouseMode(pg.ViewBox.RectMode) 
        
        graph_layout.addWidget(self.graphWidget)

        # 십자선
        self.vLine = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen('#555', width=1, style=Qt.DashLine))
        self.hLine = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen('#555', width=1, style=Qt.DashLine))
        self.graphWidget.addItem(self.vLine, ignoreBounds=True)
        self.graphWidget.addItem(self.hLine, ignoreBounds=True)

        self.proxy = pg.SignalProxy(self.graphWidget.scene().sigMouseMoved, rateLimit=60, slot=self.mouseMoved)

        main_layout.addWidget(side_widget)
        main_layout.addLayout(graph_layout)
        self.setLayout(main_layout)
        self.resize(1500, 900)

    def setAllCheckState(self, state):
        self.columnList.blockSignals(True)
        for i in range(self.columnList.count()):
            item = self.columnList.item(i)
            item.setCheckState(state)
            if item.text() in self.plot_items:
                self.plot_items[item.text()].setVisible(state == Qt.Checked)
        self.columnList.blockSignals(False)
        self.updateInfoLabel()
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

                for i, col_name in enumerate(self.df.columns[1:]):
                    item = QListWidgetItem(col_name)
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Unchecked)
                    # 아이템에 색상 정보 저장
                    color = self.colors[i % len(self.colors)]
                    item.setData(Qt.UserRole, color)
                    self.columnList.addItem(item)
                    
                    y_data = self.df[col_name].to_numpy()
                    plot = pg.PlotDataItem(self.x_timestamps, y_data, 
                                           pen=pg.mkPen(color=color, width=1.5), 
                                           name=col_name, skipFiniteCheck=True)
                    plot.hide()
                    self.graphWidget.addItem(plot)
                    self.plot_items[col_name] = plot

                self.graphWidget.autoRange()
                self.infoLabel.setText("항목을 선택하면 여기에 정보가 표시됩니다.")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"로드 실패: {str(e)}")

    def updatePlots(self, item):
        col_name = item.text()
        if col_name in self.plot_items:
            self.plot_items[col_name].setVisible(item.checkState() == Qt.Checked)
            self.updateInfoLabel()
            self.graphWidget.autoRange()

    def updateInfoLabel(self):
        """선택된 항목들만 모아서 상단에 색상 코드로 표시"""
        selected_text = "<b>선택된 항목:</b> "
        active_items = []
        for i in range(self.columnList.count()):
            item = self.columnList.item(i)
            if item.checkState() == Qt.Checked:
                color = item.data(Qt.UserRole)
                active_items.append(f"<span style='color:{color};'>■ {item.text()}</span>")
        
        if active_items:
            self.infoLabel.setText(selected_text + " | ".join(active_items))
        else:
            self.infoLabel.setText("선택된 데이터가 없습니다.")

    def mouseMoved(self, evt):
        pos = evt[0]
        if self.graphWidget.sceneBoundingRect().contains(pos) and self.df is not None:
            mousePoint = self.graphWidget.plotItem.vb.mapSceneToView(pos)
            index = np.searchsorted(self.x_timestamps, mousePoint.x())
            
            if 0 <= index < len(self.df):
                date_str = datetime.fromtimestamp(self.x_timestamps[index]).strftime('%Y-%m-%d %H:%M:%S')
                tooltip_text = f"<b>📅 {date_str}</b>"
                
                any_checked = False
                for i in range(self.columnList.count()):
                    item = self.columnList.item(i)
                    if item.checkState() == Qt.Checked:
                        col = item.text()
                        color = item.data(Qt.UserRole)
                        tooltip_text += f"<br/><span style='color:{color};'>● {col}: {self.df[index, col]:.4f}</span>"
                        any_checked = True
                
                if any_checked:
                    self.tooltip.setText(tooltip_text)
                    self.tooltip.adjustSize()
                    global_pos = self.mapFromGlobal(self.graphWidget.mapToGlobal(pos.toPoint()))
                    self.tooltip.move(global_pos.x() + 20, global_pos.y() + 20)
                    self.tooltip.show()
                    self.vLine.setPos(mousePoint.x())
                    self.hLine.setPos(mousePoint.y())
                else:
                    self.tooltip.hide()
        else:
            self.tooltip.hide()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = FinalAnalysisApp()
    ex.show()
    sys.exit(app.exec_())
