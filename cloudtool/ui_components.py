"""Shared presentation components; no network or domain logic."""
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import QComboBox, QLineEdit, QPlainTextEdit, QSizePolicy, QLabel, QPushButton, QFrame, QVBoxLayout, QFormLayout


def table(model):
    from PySide6.QtWidgets import QTableView, QAbstractItemView, QHeaderView
    w = QTableView()
    w.setModel(model)
    w.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    w.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    w.setAlternatingRowColors(True)
    w.setSortingEnabled(False)
    w.setWordWrap(False)
    w.verticalHeader().hide()
    w.verticalHeader().setDefaultSectionSize(34)
    w.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    w.horizontalHeader().setStretchLastSection(True)
    return w

def combo(items):
    widget = QComboBox()
    widget.addItems([str(x) for x in items])
    return widget


def number_input(minimum, maximum, value, suffix='', decimals=None, width=108):
    """Consistent keyboard-editable numeric field without native arrow fragments."""
    from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox, QAbstractSpinBox
    widget = QSpinBox() if decimals is None else QDoubleSpinBox()
    if decimals is not None:
        widget.setDecimals(decimals)
        widget.setSingleStep(0.1)
    widget.setRange(minimum, maximum)
    widget.setValue(value)
    widget.setSuffix(suffix)
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setFixedWidth(width)
    widget.setMinimumHeight(24)
    widget.setToolTip('直接输入数值，或使用键盘上下键调整')
    return widget


def line(placeholder=""):
    w = QLineEdit()
    w.setPlaceholderText(placeholder)
    return w


def editor(text="", height=130):
    w = QPlainTextEdit(text)
    w.setMinimumHeight(height)
    w.setMaximumHeight(height)
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return w


class DomainEditor(QPlainTextEdit):
    """Keep at least five complete lines visible, including after font/DPI changes."""
    def __init__(self, rows=5):
        super().__init__()
        self.rows = max(5, rows)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(140)

    def update_height(self):
        # Measure actual stylesheet/frame/scrollbar overhead rather than guessing pixels.
        # During first show Qt may not have laid out the viewport yet.
        overhead = max(24, self.height() - self.viewport().height())
        height = self.rows * self.fontMetrics().lineSpacing() + int(2 * self.document().documentMargin()) + overhead + 2
        self.setFixedHeight(height)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.update_height)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            QTimer.singleShot(0, self.update_height)


def label(text, name="muted"):
    w = QLabel(text)
    w.setObjectName(name)
    w.setWordWrap(True)
    return w


def button(text, callback, primary=False):
    w = QPushButton(text)
    if primary:
        w.setObjectName("primary")
    w.clicked.connect(callback)
    return w


def card():
    w = QFrame()
    w.setObjectName("card")
    layout = QVBoxLayout(w)
    layout.setContentsMargins(16, 12, 16, 12)
    layout.setSpacing(10)
    return w, layout


class AlignedForm(QFormLayout):
    """One label gutter for every page, including inserted and action rows."""
    def __init__(self):
        super().__init__()
        self.setHorizontalSpacing(14)
        self.setVerticalSpacing(12)
        self.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        self.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)

    def args(self, args):
        if len(args) == 1:
            args = ("", args[0])
        if isinstance(args[0], str):
            text = QLabel(args[0])
            text.setFixedWidth(116)
            text.setWordWrap(True)
            args = (text, args[1])
        return args

    def addRow(self, *args):
        super().addRow(*self.args(args))

    def insertRow(self, row, *args):
        super().insertRow(row, *self.args(args))


