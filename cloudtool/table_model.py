"""Reusable Qt table presentation model; does not execute business operations."""
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtGui import QColor

class TableModel(QAbstractTableModel):
    def __init__(self, columns, rows=None, centered=False):
        super().__init__()
        self.columns, self.rows = columns, rows or []
        self.centered = centered

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.TextAlignmentRole and self.centered:
            return Qt.AlignmentFlag.AlignCenter
        key = self.columns[index.column()][0]
        value = self.rows[index.row()].get(key, "")
        if role == Qt.ItemDataRole.DisplayRole:
            text = str(value)
            return text if len(text) <= 240 else text[:240] + "…（双击查看）"
        if role == Qt.ItemDataRole.ToolTipRole:
            return str(value)[:2000]
        if role == Qt.ItemDataRole.ForegroundRole and key == "state":
            return QColor({"成功": "#25805d", "已完成": "#25805d", "采集失败": "#be4147", "未通过验收": "#a36514", "部分完成": "#a36514", "失败": "#be4147", "结果未知": "#a36514", "执行中": "#3279b4", "采集中": "#3279b4"}.get(value, "#63758c"))
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][1]
        return None

    def reset(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()


