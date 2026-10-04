"""Template-management view; verification and persistence remain outside Qt."""
from datetime import datetime
from pathlib import Path
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QHeaderView
from ..ui_components import label,button,table
from ..table_model import TableModel
from .recovery import LABELS


class TemplatePanel(QWidget):
    def __init__(self,refresh,release,resume):
        super().__init__()
        layout=QVBoxLayout(self);layout.setContentsMargins(0,6,0,0)
        bar=QHBoxLayout();hint=label('当前账户的模板绑定及释放历史');hint.setWordWrap(False);bar.addWidget(hint);bar.addStretch()
        bar.addWidget(button('刷新并核实',refresh))
        self.resume_button=button('继续任务',lambda:resume(self.selected()['target']))
        self.release_button=button('核实并释放',lambda:release(self.selected()))
        bar.addWidget(self.resume_button);bar.addWidget(self.release_button);layout.addLayout(bar)
        layout.addWidget(label('原站点存在时保持占用；核实删除后才可释放。历史记录保留，失败或断网不会释放。','notice'))
        self.model=TableModel([('name','模板'),('target','原绑定站点'),('site_id','站点 ID'),('management_state','状态'),('released_at','释放时间')],centered=True)
        self.view=table(self.model);self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch);layout.addWidget(self.view,1)
        self.detail=label('选择模板查看完整目录及指纹。');layout.addWidget(self.detail)
        self.view.selectionModel().currentRowChanged.connect(self.changed);self.changed()

    def selected(self):
        index=self.view.currentIndex().row()
        return self.model.rows[index] if 0<=index<len(self.model.rows) else {}

    def changed(self,*_):
        row=self.selected();active=row.get('kind')=='active'
        self.resume_button.setEnabled(active and row.get('stage') in LABELS)
        self.release_button.setEnabled(active and bool(row.get('site_id')))
        self.detail.setText(f"目录：{row['path']}\n内容指纹：{row['digest']}" if row else '选择模板查看完整目录及指纹。')

    def show_rows(self,rows):
        for row in rows:
            row['name']=Path(row['path']).name
            row['released_at']=datetime.fromtimestamp(row['released']).strftime('%Y-%m-%d %H:%M:%S') if row.get('released') else '—'
        self.model.reset(rows);self.changed()
