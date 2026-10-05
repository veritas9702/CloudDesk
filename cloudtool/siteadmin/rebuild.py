"""One user-authorized replacement attempt, with preflight before destructive work."""
import json
import codecs
import tempfile
from pathlib import Path
from html.parser import HTMLParser
from copy import deepcopy
from ..models import Action,Plan,Cancelled,ApiError
from ..execution import execute
from .templates import template_paths,files,digest,pack
from .template_workflow import TemplateSteps,STAGES as UPLOAD_STAGES,TITLES as UPLOAD_TITLES
from .pipeline import PipelineSteps
from .pipeline_api import PipelineAPI,STAGES,TITLES
from .recovery_policy import template_failure


class BodyProbe(HTMLParser):
    def __init__(self):super().__init__();self.found=False
    def handle_starttag(self,tag,attrs):
        if tag=='body':self.found=True


def validate_injection_template(path,cancel,progress=None):
    for file in files(path,cancel,progress):
        if file.suffix.lower() not in ('.html','.htm'):continue
        probe=BodyProbe()
        with file.open('rb') as stream:
            head=stream.read(4);stream.seek(0)
            encoding='utf-32' if head.startswith((codecs.BOM_UTF32_LE,codecs.BOM_UTF32_BE)) else ('utf-16' if head.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)) else 'latin1')
            decoder=codecs.getincrementaldecoder(encoding)()
            while block:=stream.read(65536):
                if cancel.is_set():raise Cancelled()
                # HTML structural delimiters are ASCII in the supported UTF-8/legacy encodings.
                probe.feed(decoder.decode(block))
            probe.feed(decoder.decode(b'',final=True))
        probe.close()
        if not probe.found:raise ValueError(f'{file.relative_to(path)}：缺少 <body>，不能用于 H1 / 占位符加工')


class RebuildWorkflow:
    def __init__(self,client,store,usage,checkpoints):
        self.client,self.store,self.usage,self.db=client,store,usage,checkpoints

    def preview_job(self,targets,root):
        targets=tuple(dict.fromkeys(targets))
        def run(emit):
            emit=emit or (lambda *a:None)
            self.client.login();remote={r['code']:r for r in self.client.sites()}
            used=self.usage.rows()+self.usage.excluded();blocked_digests={r['digest'] for r in used};blocked_paths={r['path'] for r in used}
            candidates=iter(template_paths(root));actions=[];issues=[]
            for target in targets:
                try:
                    if self.db.rebuild(self.client.key,target):raise ValueError('已重建过一次；第二次问题请导出报告人工处理')
                    publication = self.db.step(self.client.key,target,'publish')
                    if publication.get('task_id') or publication.get('state') == 'submitting':
                        raise ValueError('站点已提交发布，请核对发布任务与线上版本；禁止自动删除重建')
                    row=remote.get(target)
                    if not row:raise ValueError('未找到原站点，不能自动重建')
                    if self.client.publication(row['id'])!='未发布':raise ValueError('站点已有发布版本，不自动删除线上站点；请人工处理')
                    tdk=self.db.allocation(self.client.key,target)
                    if not tdk:
                        for attempt in range(5):
                            try:tdk=self.db.allocate(self.client.key,target,PipelineAPI(self.client).generate());break
                            except ValueError:
                                if attempt==4:raise
                    chosen=None;reasons=[]
                    for path in candidates:
                        if str(path) in blocked_paths:continue
                        try:
                            emit('@request','重建预检',f'{target} · 检查替换模板 {path.name}')
                            validate_injection_template(path,self.client.cancel)
                            value=digest(path,self.client.cancel,progress=lambda msg:emit('@request','重建预检',msg))
                            if value in blocked_digests:continue
                            chosen=dict(path=str(path),digest=value,name=path.name)
                            # Verify actual ZIP limit before offering any deletion plan.
                            with tempfile.TemporaryDirectory(prefix='clouddesk-preflight-') as temp:
                                pack(chosen,Path(temp)/'check.zip',self.client.cancel)
                            break
                        except ValueError as exc:reasons.append(self.client.safe(exc))
                    if not chosen:raise ValueError('没有其他通过预检且未使用的模板。'+'；'.join(reasons[-3:]))
                    blocked_digests.add(chosen['digest']);blocked_paths.add(chosen['path'])
                    body=dict(site={k:row[k] for k in ('code','name','primary_domain','link_protocol')},old_id=row['id'],
                              site_id=0,existing_id=0,template=chosen,template_digest=chosen['digest'],tdk=tdk)
                    for stage,title in [('prepare','重建前复查替换模板'),('delete','删除失败站点及其远端目录'),*zip(UPLOAD_STAGES,UPLOAD_TITLES),*zip(STAGES,TITLES)]:
                        actions.append(Action(target,'REBUILD',stage,deepcopy(body),summary='重建一次 · '+title))
                except (ValueError,ApiError) as exc:
                    issues.append(dict(target=target,summary='重建需人工处理',state='需处理',detail=self.client.safe(exc)))
            return Plan(self.client.key,actions),issues
        return run

    def execute_job(self,plan,workers=1):
        snapshot=deepcopy(plan)
        def run(emit):
            self.client.login()
            ids={(a.target,a.path):a.id for a in snapshot.actions}
            with tempfile.TemporaryDirectory(prefix='clouddesk-rebuild-') as temp:
                templates=TemplateSteps(self.client,self.usage,Path(temp),
                    lambda target,sent,total:emit(ids[target,'upload'],'执行中',json.dumps(dict(upload_progress=int(sent*100/total) if total else 0,sent=sent,total=total))),reservation=snapshot.batch)
                pipeline=PipelineSteps(self.client,self.usage,self.db,{},lambda target,stage,msg:emit(ids[target,stage],'执行中',msg))
                owner=self
                class Adapter:
                    title='失败站点重建一次'
                    key,cancel=owner.client.key,owner.client.cancel
                    safe=staticmethod(owner.client.safe)
                    def request(inner,method,stage,body):
                        target=body['site']['code'];template=body['template']
                        if method!='REBUILD':raise ValueError('无效重建操作')
                        if stage=='prepare':
                            if owner.db.rebuild(inner.key,target):raise ValueError('已使用一次重建机会，请人工处理')
                            validate_injection_template(Path(template['path']),inner.cancel)
                            pack(template,Path(temp)/(template['digest']+'.zip'),inner.cancel)
                            owner.usage.reserve_replacement(template,inner.key,target,snapshot.batch)
                            templates.prepared.add(template['digest'])
                            return {'result':'替换模板及压缩包已复查，尚未删除原站点'}
                        if stage=='delete':
                            matches=[r for r in owner.client.sites(target) if r['code']==target]
                            if len(matches)!=1 or matches[0]['id']!=body['old_id'] or any(matches[0].get(k)!=v for k,v in body['site'].items()):
                                raise ValueError('原站点已变化，已停止删除')
                            if owner.client.publication(body['old_id'])!='未发布':raise ValueError('站点已发布，已停止删除')
                            owner.db.claim_rebuild(inner.key,target,dict(old_id=body['old_id'],template=template,reason='已授权的一次重建'))
                            try:owner.client.delete_site(body['old_id'],target)
                            except Exception as exc:raise ApiError(owner.client.safe(exc)+'；删除结果待核实，不自动再次删除，请人工处理',uncertain=True) from None
                            if any(r['id']==body['old_id'] or r['code']==target for r in owner.client.sites(target)):
                                raise ValueError('未确认原站点已删除，停止重建，请人工处理')
                            entry=owner.usage.entry(inner.key,target)
                            if entry:
                                owner.usage.quarantine(entry,'失败后换模板重建，原模板需人工核验')
                                owner.usage.release_verified(entry)
                            owner.db.reset_steps_for_rebuild(inner.key,target)
                            return {'result':'已核实原站点删除；保留旧模板本地文件和审计，TDK 原值保留'}
                        if stage in UPLOAD_STAGES:return templates.request('WORKFLOW',stage,body)
                        if stage in STAGES:return pipeline.request(stage,body)
                        raise ValueError('无效重建步骤')
                try:execute(Adapter(),self.store,snapshot,workers,emit)
                finally:self.usage.release_replacements(snapshot.batch)
        return run

    def after_job(self,job,initial_failures,root,workers):
        def run(emit):
            failures=set(initial_failures)
            def capture(aid,state,detail):
                emit(aid,state,detail)
                if state in ('失败','结果未知'):
                    row=self.store.history_detail(aid)
                    if row and template_failure(row['path'],state,detail):failures.add(row['target'])
            job(capture)
            if self.client.cancel.is_set() or not failures:return
            plan,issues=self.preview_job(sorted(failures),root)(emit)
            emit('@rebuild-plan','重建',json.dumps(dict(actions=[dict(id=a.id,target=a.target,stage=a.path,summary=a.summary,detail='替换模板：'+a.body['template']['path']) for a in plan.actions],issues=issues),ensure_ascii=False))
            if plan.actions:self.execute_job(plan,workers)(emit)
        return run
