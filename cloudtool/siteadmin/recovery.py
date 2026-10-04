"""Explicit user-directed recovery; never releases a template to another site."""
import json
from pathlib import Path
from .models import Site
from .template_workflow import TemplateWorkflow

LABELS={'sync_failed':'目录已同步，脚本注入失败','reserved':'打包 / 建站未完成','creating':'建站结果待核实','created':'上传尚未完成',
        'uploading':'上传结果待核实','uploaded':'待同步','syncing':'同步结果待核实',
        'synced':'待扫描','scaning':'扫描结果待核实','scanning':'扫描结果待核实'}


class RecoveryController:
    def __init__(self,client,store,usage):
        if client.key!=store.key: raise ValueError('账户不一致')
        self.client,self.store,self.usage=client,store,usage

    def entries(self):
        return [r for r in self.usage.rows() if r['owner']==self.client.key and r['stage'] in LABELS]

    def job(self,entry,completed=False):
        entry=dict(entry)
        def run(emit):
            if entry not in self.entries(): raise ValueError('恢复目标已变化或不属于当前账户')
            self.client.login()
            matches=[r for r in self.client.sites(entry['target']) if r['code']==entry['target']]
            data=self.store.latest_payload(entry['target'],'WORKFLOW')
            site=Site(**data['site']) if isinstance(data,dict) and 'site' in data else None
            if site is None:
                raise ValueError('原流程配置缺失，无法安全恢复。请保留当前绑定和任务数据库，不要重新分配模板。')
            if matches and (len(matches)!=1 or any(matches[0].get(k)!=v for k,v in site.body().items())):
                raise ValueError('远端站点配置与原流程不一致，停止恢复')
            stage=entry['stage'];site_id=entry['site_id']
            if stage in ('reserved','creating'):
                stage='created' if matches else 'reserved';site_id=matches[0]['id'] if matches else 0
            else:
                if not matches or matches[0]['id']!=site_id:raise ValueError('站点不存在或 ID 已变化，不能恢复到其他站点')
                choices={'sync_failed':('uploaded','synced'),'uploading':('created','uploaded'),'syncing':('uploaded','synced'),
                         'scaning':('synced','done'),'scanning':('synced','done')}
                if stage in choices:stage=choices[stage][int(completed)]
            if stage=='created' and matches and matches[0].get('page_count')!=0:
                raise ValueError('站点已有扫描页面，不能重传覆盖。请核实后选择“该步骤已完成”。')
            self.usage.recover(entry,stage,site_id)
            template=dict(path=entry['path'],digest=entry['digest'],name=Path(entry['path']).name)
            return TemplateWorkflow(self.client,self.store,self.usage).preview_job((site,),str(Path(entry['path']).parent),[template])(emit)
        return run
