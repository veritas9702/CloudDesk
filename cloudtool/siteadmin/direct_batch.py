"""One-click bounded site queue, composing the existing plans and execution."""
import json
import threading
from ..execution import bounded_map
from ..models import ApiError, Cancelled
from .pipeline import SitePipeline
from .rebuild import RebuildWorkflow


from .recovery_policy import template_failure


class DirectBatch:
    def __init__(self, client, store, usage, checkpoints):
        self.client, self.store, self.usage, self.db = client, store, usage, checkpoints
        self.pipeline = SitePipeline(client,store,usage,checkpoints)

    def job(self, sites, root='', upload=False, workers=1, rebuild=True):
        sites = tuple(sites)
        def run(emit):
            self.client.login()
            remote = self.client.sites()
            ready, rebuild_targets = [], set()
            planning, upload_slot, result_lock = threading.Lock(), threading.Lock(), threading.Lock()
            def issue(target, detail):
                emit('@direct-issue:'+target,'需处理',str(detail))
            # Freeze all TDK before content writes; no template library scan here.
            for i, site in enumerate(sites,1):
                if self.client.cancel.is_set(): raise Cancelled()
                emit('@preview:'+site.code,'分配 TDK',f'{i}/{len(sites)} · 固定站点专属 TDK')
                try:
                    self.pipeline.allocate_tdk(site.code)
                    ready.append(site)
                except (ValueError,ApiError) as exc:
                    issue(site.code,self.client.safe(exc))

            def one(site):
                if self.client.cancel.is_set(): raise Cancelled()
                try:
                    # Serialize allocation only; earlier sites execute while the next
                    # template is being checked. Reserve before releasing the lock.
                    while not planning.acquire(timeout=.1):
                        if self.client.cancel.is_set(): raise Cancelled()
                    try:
                        if self.client.cancel.is_set(): raise Cancelled()
                        plan, issues = self.pipeline.preview_job((site,),root,upload,remote)(emit)
                        for action in plan.actions:
                            if action.method == 'WORKFLOW' and action.path == 'pack':
                                self.usage.reserve(action.body['template'],self.client.key,site.code)
                    finally:
                        planning.release()
                    if not plan.actions:
                        issue(site.code,'；'.join(r['detail'] for r in issues) or '没有可执行步骤')
                        return
                    emit('@direct-plan:'+site.code,'就绪',json.dumps([
                        dict(id=a.id,target=a.target,stage=a.path,summary=a.summary)
                        for a in plan.actions],ensure_ascii=False))
                    actions = {a.id:a for a in plan.actions}
                    def progress(aid,state,detail):
                        emit(aid,state,detail)
                        action = actions.get(aid)
                        if action and template_failure(action.path,state,detail):
                            with result_lock: rebuild_targets.add(site.code)
                    self.pipeline.execute_job(plan,1,remote,upload_slot)(progress)
                except Cancelled:
                    raise
                except Exception as exc:
                    issue(site.code,self.client.safe(exc))
            list(bounded_map(one,ready,max(1,min(4,workers)),self.client.cancel))
            if rebuild and rebuild_targets and not self.client.cancel.is_set():
                if not root:
                    for target in rebuild_targets: issue(target,'模板问题：未配置备用模板父目录；请配置后恢复。')
                    return
                recovery = RebuildWorkflow(self.client,self.store,self.usage,self.db)
                # Existing recovery verifies unpublished status and enforces the
                # durable one-attempt limit before any deletion.
                recovery.after_job(lambda report:None,sorted(rebuild_targets),root,workers)(emit)
        return run
