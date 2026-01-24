from PySide6.QtWidgets import QApplication, QWidget
import sys
import MainWindow as mw

app = QApplication(sys.argv)
window = mw.MainWindow()
window.show()  
app.exec()