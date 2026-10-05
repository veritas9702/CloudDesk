"""TDK-first orchestration. Site workers are bounded; each site's stages are serial."""
import json
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from ..models import Action, Plan, ApiError, Cancelled, canonical, fingerprint
from ..execution import execute
from .controller import related
from .template_workflow import TemplateWorkflow, TemplateSteps
from .pipeline_api import PipelineAPI, STAGES, TITLES


class SitePipeline:
    def __init__(self, client, store, usage, checkpoints):
        if client.key != store.key: raise ValueError('后台账户不匹配')
        self.client, self.store, self.usage, self.checkpoints = client, store, usage, checkpoints

    def allocate_tdk(self, target):
        tdk = self.checkpoints.allocation(self.client.key,target)
        if tdk: return tdk
        for attempt in range(5):
            candidate = PipelineAPI(self.client).generate()
            try: return self.checkpoints.allocate(self.client.key,target,candidate)
            except ValueError:
                if attempt == 4: raise ValueError('词库连续生成重复标题，请扩充词库后重试')

    def preview_job(self, sites, root='', upload=False, remote_snapshot=None):
        sites = tuple(sites)
        def run(emit):
            emit = emit or (lambda *args: None)
            if remote_snapshot is None:
                self.client.login(); remote = self.client.sites()
            else: remote = deepcopy(remote_snapshot)
            owned = {e['target']:e for e in self.usage.rows() if e['owner']==self.client.key}
            prepared, skipped, need_upload = {}, [], []
            for index, site in enumerate(sites, 1):
                if self.client.cancel.is_set(): raise Cancelled()
                emit('@preview:'+site.code, '分配 TDK', f'{index}/{len(sites)} · 先保存专属 TDK')
                try:
                    matches = related(remote, site.body())
                    if len(matches)>1: raise ValueError('后台存在多个匹配站点，请先核对')
                    row = matches[0] if matches else None
                    if row and any(row.get(k)!=site.body()[k] for k in ('code','primary_domain','link_protocol')):
                        raise ValueError('已有站点配置与输入不一致，请核对泛域名和协议设置')
                    entry = owned.get(site.code)
                    if entry and entry['stage'] != 'done' and not upload:
                        raise ValueError('原模板流程尚未完成，请先恢复同步 / 扫描')
                    needs = not row or row.get('page_count', 0)==0 or entry and entry['stage']!='done'
                    if needs and not upload: raise ValueError('站点尚无可用页面，请先勾选上传模板并完成同步扫描')
                    if not needs and (type(row.get('page_count')) is not int or row['page_count']<=0):
                        raise ValueError('无法确认已有模板的页面数')
                    tdk = self.allocate_tdk(site.code)
                    site_body={k:row[k] for k in site.body()} if row and not needs else site.body()
                    prepared[site.code] = dict(site=site_body,site_id=row['id'] if row else 0,tdk=tdk,
                                              template_digest=entry['digest'] if entry else '')
                    if needs: need_upload.append(site)
                    emit('@preview:'+site.code,'TDK 已保存',tdk['title'])
                except (ValueError, ApiError) as exc:
                    detail = self.client.safe(exc)
                    skipped.append(dict(target=site.code,summary='六步预览未通过',state='需处理',detail=detail))
                    emit('@preview:'+site.code,'需处理',detail)
            template_actions = {}
            if need_upload:
                try:
                    plan, issues = TemplateWorkflow(self.client,self.store,self.usage).preview_job(
                        need_upload,root,remote_snapshot=remote)(emit)
                except ValueError as exc:
                    plan = Plan(self.client.key,[])
                    issues = [dict(target=s.code,summary='模板预览未通过',state='需处理',detail=self.client.safe(exc)) for s in need_upload]
                for a in plan.actions: template_actions.setdefault(a.target,[]).append(a)
                for issue in issues:
                    if issue['state']!='已跳过': prepared.pop(issue['target'],None); skipped.append(issue)
            actions = []
            for site in sites:
                payload = prepared.get(site.code)
                if not payload: continue
                initial = template_actions.get(site.code,[])
                if initial: payload['template_digest'] = initial[0].body['template']['digest']
                actions.extend(initial)
                for stage, title in zip(STAGES,TITLES):
                    actions.append(Action(site.code,'PIPELINE',stage,deepcopy(payload),summary=title))
                emit('@preview:'+site.code,'预览就绪','TDK 已固定；已有模板和已完成步骤会跳过')
            return Plan(self.client.key,actions),skipped
        return run

    def attach_task_job(self,target,stage,task_id):
        def run(emit):
            saved = self.checkpoints.step(self.client.key,target,stage)
            if saved.get('state')!='submitting' or saved.get('task_id'):
                raise ValueError('此步骤没有待核实的提交')
            self.client.login()
            PipelineAPI(self.client).task(task_id,saved['site_id'],stage)
            self.checkpoints.save(self.client.key,target,stage,**dict(saved,state='running',task_id=task_id))
            return '任务身份核对通过，已保存任务 ID；重新预览后继续查询原任务'
        return run

    def execute_job(self, plan, workers=1, remote_snapshot=None, upload_slot=None):
        snapshot = deepcopy(plan)
        def run(emit):
            if snapshot.owner != self.client.key: raise ValueError('计划属于其他后台')
            if remote_snapshot is None:
                self.client.login(); rows = self.client.sites()
            else: rows = remote_snapshot
            remote = {r['id']:r for r in rows}
            ids = {(a.target,a.path):a.id for a in snapshot.actions}
            with tempfile.TemporaryDirectory(prefix='clouddesk-template-') as temp:
                template = TemplateSteps(self.client,self.usage,Path(temp),
                    lambda target,sent,total: emit(ids[(target,'upload')],'执行中',json.dumps(
                        dict(upload_progress=int(sent*100/total) if total else 0,sent=sent,total=total))))
                if upload_slot is not None: template.upload_slot = upload_slot
                pipeline = PipelineSteps(self.client,self.usage,self.checkpoints,remote,
                    lambda target,stage,text: emit(ids[(target,stage)],'执行中',text))
                class Adapter:
                    title = 'TDK 优先站点流程'
                    key, cancel = self.client.key, self.client.cancel
                    safe = staticmethod(self.client.safe)
                    def request(inner,method,stage,body):
                        if method=='WORKFLOW': return template.request(method,stage,body)
                        if method=='PIPELINE': return pipeline.request(stage,body)
                        raise ValueError('无效的流程操作')
                execute(Adapter(),self.store,snapshot,workers,emit)
        return run


class PipelineSteps:
    poll_interval = 1.5
    wait_limit = 1800

    def __init__(self,client,usage,checkpoints,remote,report):
        self.client,self.usage,self.db,self.remote,self.report = client,usage,checkpoints,remote,report
        self.api = PipelineAPI(client)
        self.owner = client.key

    def request(self, stage, payload):
        if stage not in STAGES: raise ValueError('无效加工步骤')
        target = payload['site']['code']
        entry = self.usage.entry(self.owner,target)
        site_id = payload['site_id']
        if payload['template_digest']:
            if not entry or entry['stage']!='done' or entry['digest']!=payload['template_digest']:
                raise ValueError('模板尚未成功同步和扫描，禁止执行后续加工')
            site_id = entry['site_id']
        # Existing sites are checked once per batch, not once per stage/page.
        if payload['site_id']:
            row = self.remote.get(site_id)
            if not row or any(row.get(k)!=v for k,v in payload['site'].items()):
                raise ValueError('站点在预览后发生变化，请重新预览')
        if not site_id: raise ValueError('缺少已扫描站点 ID')
        tdk = self.db.allocation(self.owner,target)
        if tdk != payload['tdk']: raise ValueError('TDK 分配已变化，请重新预览')
        signature = fingerprint(canonical(dict(site_id=site_id,site=payload['site'],tdk=tdk,
                                              template=payload['template_digest'],version=1)))
        saved = self.db.step(self.owner,target,stage)
        if saved and saved.get('signature')!=signature:
            raise ValueError('站点 / 模板 / 配置与原加工记录不同，需核对旧流程，不能重放')
        if saved.get('state')=='done': return {'result':'此步骤已完成，跳过；TDK 保持原分配'}
        for previous in STAGES[:STAGES.index(stage)]:
            checkpoint = self.db.step(self.owner,target,previous)
            if checkpoint.get('state')!='done' or checkpoint.get('signature')!=signature:
                raise ValueError('前置步骤尚未成功，尤其 TDK 必须先完成')
        record = dict(signature=signature,site_id=site_id,state='prepared',task_id=0)
        report = lambda text: self.report(target,stage,text)
        body = dict(site_id=site_id)
        if stage=='tdk': body.update(tdk)
        elif stage=='convert': body['skip_tdk']=True
        elif stage=='h1': body.update(template='{{title}}',enabled=True,**{'class':''})
        if saved.get('state')=='failed' and not saved.get('task_id') and saved.get('body',{}).get('rel_paths'):
            body['rel_paths']=saved['body']['rel_paths']
        if saved.get('task_id'):
            task = self.api.task(saved['task_id'],site_id,stage)
            if saved.get('state')!='failed':
                return self.wait(target,stage,saved,report,task)
            if stage == 'publish':
                # Publication may already have switched the live version before
                # a desktop-page/nginx failure. Reconcile the original task only.
                return self.wait(target,stage,saved,report,task)
            # User explicitly previewed/executed recovery. Never repeat successful conversion files.
            if task.get('status') not in ('failed','partial','canceled','interrupted'):
                return self.wait(target,stage,saved,report,task)
            if stage!='tdk':
                items = self.api.paged(f"/api/tasks/{saved['task_id']}/items")
                paths = [r.get('rel_path') for r in items]
                if len(items)!=task.get('total') or any(not p for p in paths) or len(set(paths))!=len(paths):
                    raise ValueError('后台失败任务明细不完整；保留断点，请先核实后台，避免重复转换成功页面')
                if task.get('needs_review',0) or any(r.get('status') not in ('success','unchanged','failed') for r in items):
                    raise ValueError('任务仍有待复核或未确定的文件，需先核实后台，不能遗漏后直接继续')
                failures = [r['rel_path'] for r in items if r.get('status')=='failed']
                if not failures or len(failures)!=task.get('failed'):
                    raise ValueError('后台失败数量与明细不一致，不能自动重放；请检查任务中心')
                body['rel_paths']=failures
            record['previous_task_id']=saved['task_id']
        elif saved.get('state')=='submitting':
            raise ApiError('上次提交结果待核实，缺少任务 ID；请使用“核对加工任务 ID”，禁止重复提交',uncertain=True)
        report('抽样预览 / 检测中')
        expected=self.db.step(self.owner,target,'tdk').get('total') if stage=='stat_clean' else None
        body,note = self.api.prepare(stage,body,report,expected_total=expected)
        report(note)
        record['preview']=note
        record['body']=body
        if stage=='stat_clean' and not body['rel_paths']:
            self.db.save(self.owner,target,stage,**dict(record,state='done',detail=note))
            return {'result':note+'；无需清理，继续下一步'}
        if self.client.cancel.is_set(): raise Cancelled()
        self.db.save(self.owner,target,stage,**dict(record,state='submitting'))
        try:
            task_id = self.api.submit(stage,body)
        except ApiError as exc:
            if not exc.uncertain: self.db.save(self.owner,target,stage,**dict(record,state='failed',detail=str(exc)))
            raise
        record.update(state='running',task_id=task_id)
        self.db.save(self.owner,target,stage,**record)
        return self.wait(target,stage,record,report)

    def wait(self,target,stage,record,report,task=None):
        deadline = time.monotonic()+self.wait_limit
        while True:
            if self.client.cancel.is_set():
                raise Cancelled('已停止客户端等待；后台任务 ID 已保存，恢复时先读取结果')
            task = task or self.api.task(record['task_id'],record['site_id'],stage)
            status = task.get('status')
            report(json.dumps(dict(task_id=record['task_id'],task_status=status,done=task.get('succeeded',0),
                                   total=task.get('total',0),failed=task.get('failed',0)),ensure_ascii=False))
            if status=='success' and type(task.get('failed')) is int and task['failed']==0 and task.get('total',0)>0 and task.get('needs_review',0)==0:
                detail=f"任务 #{record['task_id']} 完成；{record.get('preview','')}"
                self.db.save(self.owner,target,stage,**dict(record,state='done',detail=detail,total=task['total']))
                return {'result':detail}
            if status in ('success','partial','failed','canceled','interrupted'):
                detail=f"任务 #{record['task_id']}：{status}，失败 {task.get('failed','未知')}，需复核 {task.get('needs_review',0)}。修正后台原因后重新预览，只恢复未完成步骤。"
                if stage == 'publish':
                    detail=f"发布任务 #{record['task_id']}：{status}，失败 {task.get('failed','未知')}。请核对后台发布版本、电脑端页面和 Nginx；恢复仅查询原任务，不重复发布或自动重建。"
                self.db.save(self.owner,target,stage,**dict(record,state='failed',detail=detail))
                try:
                    items=self.api.paged(f"/api/tasks/{record['task_id']}/items")
                    reasons=[f"{r.get('rel_path','')}：{r.get('message','')}" for r in items if r.get('status')=='failed']
                    if reasons: detail+='\n'+'；'.join(reasons[:3])
                    self.db.save(self.owner,target,stage,**dict(record,state='failed',detail=self.client.safe(detail)))
                except Exception:
                    detail+='；未能读取文件明细，可在后台任务中心查看原因'
                raise ValueError(detail)
            if status not in ('pending','running'): raise ValueError('后台任务状态无法识别；任务 ID 已保留')
            if time.monotonic()>=deadline: raise ApiError('等待后台任务超过 30 分钟；任务 ID 已保存，恢复会继续核对',uncertain=True)
            self.client.cancel.wait(self.poll_interval)
            task=None
