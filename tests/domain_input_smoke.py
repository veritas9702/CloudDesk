"""Check actual fifth-line visibility at small sizes and with tasks expanded."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
from pathlib import Path
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication
from cloudtool.ui import Window, configure_app

app = QApplication([])
configure_app(app)
with tempfile.TemporaryDirectory() as tmp:
    window = Window(Path(tmp))
    window.resize(1120, 780)
    window.show()
    window.scope.setPlainText('\n'.join(f'domain-{n}.example' for n in range(1, 6)))
    for page in range(1, 13):
        window.nav.setCurrentRow(page)
        for expanded in (False, True):
            window.set_task_expanded(expanded)
            for _ in range(3):
                app.processEvents()
            cursor = QTextCursor(window.scope.document().findBlockByNumber(4))
            rect = window.scope.cursorRect(cursor)
            assert rect.top() >= 0 and rect.bottom() < window.scope.viewport().height(), (page, expanded, rect)
            assert window.inputs_scroll.horizontalScrollBar().maximum() == 0
            assert window.height() == 780
    window.close()
print('All 12 pages: fifth line fully visible with tasks collapsed/expanded at 1120x780')
