"""Link presentation for the site inventory; no requests or browser lifecycle."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from ..table_model import TableModel
from .site_catalog import site_visit_url


class SiteTableModel(TableModel):
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and self.columns[index.column()][0] == 'primary_domain':
            try:
                url = site_visit_url(self.rows[index.row()])
            except ValueError:
                return super().data(index, role)
            if role == Qt.ItemDataRole.ToolTipRole:
                return '点击访问 ' + url
            if role == Qt.ItemDataRole.ForegroundRole:
                return QColor('#1768b5')
            if role == Qt.ItemDataRole.FontRole:
                font = QFont(); font.setUnderline(True)
                return font
        return super().data(index, role)
