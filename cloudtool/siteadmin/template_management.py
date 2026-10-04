"""Verify remote site identity before releasing a local template allocation."""
from copy import deepcopy
from .recovery import LABELS


def present(entry,sites):
    # A recreated code is ambiguous even when its numeric ID changed.
    return any(row['id']==entry['site_id'] or row['code'].casefold()==entry['target'].casefold() for row in sites)


class TemplateManagement:
    def __init__(self,client,usage):self.client,self.usage=client,usage

    def list_job(self,emit):
        self.client.login()
        sites=self.client.sites()  # Complete, unfiltered, validated pagination; failures propagate.
        result=[]
        for entry in self.usage.rows():
            if entry['owner']!=self.client.key:continue
            exists=present(entry,sites)
            status=('占用中 · '+LABELS.get(entry['stage'],'流程已完成')) if exists else '疑似已删除 · 待核实'
            if not entry['site_id']:status='未记录站点 ID · 需先恢复核实'
            result.append(dict(entry,management_state=status,kind='active'))
        for entry in self.usage.releases(self.client.key):
            result.append(dict(entry,management_state='已释放 · 保留历史',kind='released'))
        return result

    def release_job(self,entry):
        snapshot={k:entry[k] for k in ('digest','path','owner','target','stage','site_id')}
        snapshot=deepcopy(snapshot)
        def run(emit):
            if snapshot['owner']!=self.client.key:raise ValueError('不能核实其他后台账户的模板')
            if not snapshot['site_id']:raise ValueError('缺少原站点 ID，请先恢复流程并核实站点，不能仅凭名称释放')
            if snapshot not in self.usage.rows():raise ValueError('模板绑定已变化，请刷新后重新核实')
            self.client.login()
            sites=self.client.sites()
            if present(snapshot,sites):raise ValueError('原站点仍存在，或存在同编码站点。模板保持占用，请继续原任务；页面数为 0 不代表站点已删除。')
            if self.client.cancel.is_set():raise ValueError('核实已取消，未释放模板')
            self.usage.release_verified(snapshot)
            return f"已核实原站点 {snapshot['target']}（ID {snapshot['site_id']}）不存在，模板已释放；使用历史保留。"
        return run
