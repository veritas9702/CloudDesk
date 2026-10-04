"""Template workflow composes existing audited execution; no GUI or HTTP encoding."""
import tempfile
import threading
import json
from copy import deepcopy
from pathlib import Path
from ..models import Action, Plan, ApiError, Cancelled
from ..execution import execute
from .controller import related
from .templates import inventory, pack, digest, template_paths
from .models import Site

STAGES=('pack','create','upload','sync','scan')
TITLES=('打包模板','创建 / 核对空站点','上传并解压','同步上传目录','扫描页面')
RANK={'reserved':0,'created':1,'uploaded':2,'synced':3,'done':4}


class TemplateWorkflow:
    def __init__(self, client, store, usage):
        if client.key!=store.key: raise ValueError('账户不一致')
        self.client,self.store,self.usage=client,store,usage

    def preview_job(self,sites,root,assigned=None,remote_snapshot=None):
        sites=tuple(sites)
        def run(emit):
            templates=deepcopy(assigned) if assigned is not None else None
            paths=None
            invalid=[]
            used=self.usage.rows(); owned={r['target']:r for r in used if r['owner']==self.client.key}
            if remote_snapshot is None:
                self.client.login(); remote=self.client.sites()
            else: remote=deepcopy(remote_snapshot)
            released=self.usage.releases()
            actions=[]; skipped=[]; allocated=set()
            excluded=self.usage.excluded()
            used_paths={r['path'] for r in used+excluded};used_digests={r['digest'] for r in used+excluded}
            def progress(message):
                if emit:
                    emit('@request','预览中',message)
                    if current[0]: emit('@preview:'+current[0],'校验中',message)
            current=['']
            for number,site in enumerate(sites,1):
                current[0]=site.code
                progress(f'预览 {number}/{len(sites)} · {site.code}')
                if emit:emit('@preview:'+site.code,'校验中',f'正在检查 {number}/{len(sites)}')
                try:
                    previous=owned.get(site.code)
                    if previous and previous['stage'] not in RANK:
                        raise ValueError(f'{site.code}：上次 {previous["stage"]} 结果待核实，禁止自动重复上传')
                    if previous and previous['stage']=='done':
                        skipped.append(dict(target=site.code,summary='模板流程已完成',state='已跳过',detail=previous['path']))
                        if emit:emit('@preview:'+site.code,'已跳过','模板流程已完成')
                        continue
                    matches=related(remote,site.body())
                    if len(matches)>1 or matches and any(matches[0].get(k)!=v for k,v in site.body().items()):
                        raise ValueError(f'{site.code}：站点冲突')
                    if matches and not previous and matches[0].get('page_count')!=0:
                        raise ValueError(f'{site.code}：仅支持空站点，已有页面或无法确认页面数')
                    if previous and (not matches or matches[0]['id']!=previous['site_id']) and previous['stage']!='reserved':
                        raise ValueError(f'{site.code}：先前站点已变化，请核实后台')
                    template=None
                    if templates is not None:
                        candidates=[t for t in templates if t['digest'] not in allocated and (
                            previous and t['digest']==previous['digest'] and t['path']==previous['path'] or
                            not previous and t['digest'] not in used_digests and t['path'] not in used_paths)]
                        template=candidates[0] if candidates else None
                    elif previous:
                        path=Path(previous['path'])
                        if path.parent != Path(root).expanduser().absolute():
                            raise ValueError('原模板不在所选父目录，请使用恢复流程')
                        # Uploaded content is already on the server; no local library scan is needed.
                        value=previous['digest'] if RANK[previous['stage']]>=2 else digest(path,self.client.cancel,progress=progress,cache=self.usage)
                        if value==previous['digest']:
                            template=dict(path=str(path),digest=value,name=path.name)
                    else:
                        if paths is None:paths=iter(template_paths(root))
                        for path in paths:
                            if self.client.cancel.is_set():raise Cancelled()
                            if str(path) in used_paths:continue
                            try:value=digest(path,self.client.cancel,progress=progress,cache=self.usage)
                            except (OSError, ValueError) as exc:
                                invalid.append(f'{path.name}：{exc}')
                                progress('跳过不可用模板：'+invalid[-1]);continue
                            if value in used_digests or value in allocated:continue
                            template=dict(path=str(path),digest=value,name=path.name);break
                    if template is None:
                        raise ValueError(f'{site.code}：未使用模板不足，或原模板已移动 / 修改。'+ ('；'.join(invalid[-3:]) if invalid else ''))
                    for old in released:
                        if old['digest']==template['digest'] and old['owner']!=self.client.key:
                            raise ValueError('模板存在其他后台的使用历史，请使用原后台账户核实并重新分配；当前账户不能验证其他后台。')
                        if old['digest']==template['digest'] and any(r['id']==old['site_id'] or r['code'].casefold()==old['target'].casefold() for r in remote):
                            raise ValueError('模板原绑定站点重新出现，不能重新分配；请在模板管理中核实后台。')
                    allocated.add(template['digest'])
                    payload=dict(site=site.body(),template=template,existing_id=matches[0]['id'] if matches else 0)
                    for stage,title in zip(STAGES,TITLES):
                        if stage == 'create' and payload.get('existing_id'): title = '复用已有空站点'
                        actions.append(Action(site.code,'WORKFLOW',stage,deepcopy(payload),summary=f'{title} · {template["name"]}'))
                    if emit:emit('@preview:'+site.code,'预览就绪',f'模板：{template["name"]}；等待确认执行')
                except (OSError, ValueError) as exc:
                    if emit:emit('@preview:'+site.code,'需处理',self.client.safe(exc))
                    if len(sites) == 1: raise
                    skipped.append(dict(target=site.code,summary='预览未通过',state='需处理',detail=self.client.safe(exc)))
            return Plan(self.client.key,actions),skipped
        return run

    def assign_job(self, row, folder):
        """Assign one selected template to an existing empty site; reuse audited workflow."""
        row=deepcopy(row)
        def run(emit):
            if row.get('page_count') != 0: raise ValueError('只能给空站点分配模板，请先加载最新站点列表')
            if any(r['owner']==self.client.key and r['target']==row['code'] for r in self.usage.rows()):
                raise ValueError('此站点已有模板绑定，请使用“重试 / 恢复未完成流程”，不能重新分配')
            path=Path(folder).absolute()
            self.check_available(path)
            template=dict(path=str(path),digest=digest(path,self.client.cancel),name=path.name)
            self.check_available(path,template['digest'])
            site=Site(**{key:row[key] for key in ('code','name','primary_domain','link_protocol')})
            plan,skipped=self.preview_job((site,),str(path.parent),[template])(emit)
            if not plan.actions or any(a.body['existing_id']!=row['id'] for a in plan.actions):
                raise ValueError('所选站点已删除或发生变化，请刷新列表')
            return plan,skipped
        return run

    def check_available(self,path,content_digest=None):
        if any(Path(e['path']).absolute()==path or content_digest==e['digest'] for e in self.usage.excluded()):
            raise ValueError('此模板因失败已隔离，请选择其他模板')
        for entry in self.usage.rows():
            if Path(entry['path']).absolute()==path or content_digest and entry['digest']==content_digest:
                target=f"当前后台站点 {entry['target']}" if entry['owner']==self.client.key else '另一个后台的站点'
                raise ValueError(f'模板“{path.name}”已绑定到{target}，不能再次分配。'
                                 '请选择未使用的模板；若要继续原站点的任务，请使用“重试 / 恢复未完成流程”。'
                                 '本次未上传，也未修改站点。')

    def execute_job(self,plan,workers=1):
        snapshot=deepcopy(plan)
        def run(emit):
            if snapshot.owner!=self.client.key: raise ValueError('流程属于另一个后台')
            self.client.login()
            with tempfile.TemporaryDirectory(prefix='clouddesk-template-') as temp:
                ids={(a.target,a.path):a.id for a in snapshot.actions}
                def progress(target,sent,total):
                    percent=int(sent*100/total) if total else 100
                    emit(ids[(target,'upload')],'执行中',json.dumps(dict(upload_progress=percent,sent=sent,total=total)))
                adapter=TemplateSteps(self.client,self.usage,Path(temp),progress,
                    lambda target:emit(ids[(target,'upload')],'排队中','等待上传通道；同一任务一次上传一个模板'))
                execute(adapter,self.store,snapshot,workers,emit)
        return run


class TemplateSteps:
    title='模板接入'
    def __init__(self,client,usage,temp,progress=None,waiting=None,prepared=(),reservation=''):
        self.client,self.usage,self.temp=client,usage,temp
        self.key,self.cancel=client.key,client.cancel
        self.entries={}
        self.progress=progress
        self.waiting=waiting
        self.upload_slot=threading.Lock()
        self.prepared=set(prepared)
        self.reservation=reservation
    def safe(self,message): return self.client.safe(message)

    def request(self,method,stage,body):
        if stage!='upload':return self._request(method,stage,body)
        if self.waiting:self.waiting(body['site']['code'])
        while not self.upload_slot.acquire(timeout=.1):
            if self.cancel.is_set():raise Cancelled()
        try:
            if self.cancel.is_set():raise Cancelled()
            return self._request(method,stage,body)
        finally:self.upload_slot.release()

    def _request(self,method,stage,body):
        site,template=body['site'],body['template']; target=site['code']; key=template['digest']
        if method!='WORKFLOW' or stage not in STAGES: raise ValueError('无效流程步骤')
        if stage=='pack':
            previous=[r for r in self.usage.releases() if r['digest']==key]
            if previous:
                if any(old['owner']!=self.key for old in previous):raise ValueError('模板在其他后台有使用历史，当前账户无法核实')
                remote=self.client.sites()
                if any(r['id']==old['site_id'] or r['code'].casefold()==old['target'].casefold() for old in previous for r in remote):
                    raise ValueError('原绑定站点在预览后重新出现，已停止模板重新分配')
            entry=self.usage.reserve(template,self.key,target,self.reservation)
            if entry['stage'] not in RANK: raise ValueError('上次请求结果待核实，不能重放')
            self.entries[target]=entry
            if RANK[entry['stage']]>=2: return {'result':'上传已完成，不再打包或上传'}
            try:
                if key not in self.prepared:pack(template,self.temp/(key+'.zip'),self.cancel)
            except Exception:
                self.usage.release_unstarted(key,self.key,target)
                raise
            return {'result':'模板已校验并打包；原目录未改动'}
        entry=self.entries[target]; rank=RANK[entry['stage']]
        required={'create':1,'upload':2,'sync':3,'scan':4}[stage]
        if rank>=required: return {'result':'此步骤已完成，跳过'}
        if stage=='create':
            matches=related(self.client.sites(target),site)
            if matches:
                if len(matches)!=1 or matches[0]['id']!=body['existing_id'] or any(matches[0].get(k)!=v for k,v in site.items()) or matches[0].get('page_count')!=0:
                    raise ValueError('远端空站点在预览后发生变化，请重新预览')
                site_id=matches[0]['id']
            else:
                if body['existing_id']: raise ValueError('预览的站点已不存在')
                self.usage.set(key,self.key,'creating',0)
                result=self.client.request('POST','/api/sites',site)['result'];site_id=result['id']
            entry.update(stage='created',site_id=site_id)
            self.usage.set(key,self.key,'created',site_id)
            return {'result':f'站点 ID：{site_id}'}
        # Persist the in-flight state BEFORE remote mutation. A crash must never replay an upload.
        if stage=='upload':
            matches=related(self.client.sites(target),site)
            if len(matches)!=1 or matches[0]['id']!=entry['site_id'] or matches[0].get('page_count')!=0 or any(matches[0].get(k)!=v for k,v in site.items()):
                raise ValueError('上传前站点发生变化或不再是空站点，已停止')
        self.usage.set(key,self.key,stage+'ing',entry['site_id'])
        api={'upload':'upload-template','sync':'sync','scan':'scan'}[stage]
        try:
            if stage=='upload' and self.progress:
                result=self.client.template_step(entry['site_id'],api,self.temp/(key+'.zip'),
                    progress=lambda sent,total:self.progress(target,sent,total))
            else:
                result=self.client.template_step(entry['site_id'],api,self.temp/(key+'.zip'))
            count=result.get('total' if stage=='scan' else 'file_count')
            if not isinstance(count,int) or count<=0:
                raise ValueError('后台未返回有效文件 / 页面数量，请检查模板及后台结果')
        except Exception as exc:
            if stage == 'sync' and '同步已完成' in str(exc) and '注入失败' in str(exc):
                self.usage.set(key,self.key,'sync_failed',entry['site_id'])
                raise ApiError(self.safe(exc)+'；目录已同步，脚本注入失败。修复后台注入问题后恢复同步，无需重新上传或更换模板。',uncertain=False) from None
            raise ApiError(self.safe(exc)+'；此模板仍绑定当前站点，请核实后台，禁止盲目重传',uncertain=True) from None
        complete={'upload':'uploaded','sync':'synced','scan':'done'}[stage]
        entry['stage']=complete;self.usage.set(key,self.key,complete,entry['site_id'])
        return {'result':result}
