"""Cross-step onboarding orchestration; reuse provider plans and audited executor."""
import json
import time
from copy import deepcopy
from .models import Action, ApiError, Cancelled, Plan
from .execution import bounded_map, execute
from .automation_model import WorkflowPreview


def nameservers(value):
    values = value.split(',') if isinstance(value, str) else value
    return sorted(str(v).strip().lower().rstrip('.') for v in (values or []) if str(v).strip())


class OnboardingController:
    def __init__(self, client, store, provider, registrar=None):
        if client.key != store.key:
            raise ValueError('自动化客户端和审计账户不一致')
        self.client, self.store, self.provider, self.registrar = client, store, provider, registrar
        if registrar:
            # This client belongs only to this workflow, never the GNAME workspace.
            registrar.cancel = client.cancel

    def zone(self, name, account):
        matches = [z for z in self.client.all('/zones', {'name': name, 'account.id': account})
                   if z.get('name') == name and z.get('account', {}).get('id') == account]
        if len(matches) > 1: raise ValueError(f'{name}：目标账户存在多个 Zone，停止自动选择')
        if matches and matches[0].get('type') != 'full':
            raise ValueError(f'{name}：自动化只支持 Full Zone')
        return matches[0] if matches else None

    def stage_plan(self, zone, site, options, stage):
        if stage == 'dns':
            return self.provider.plan([zone], 'dns_upsert', {
                'records': json.dumps(options.records(site)), 'dns_batch': False}, 1)
        return self.provider.plan([zone], 'settings', {'values': options.settings()}, 1)

    def preview(self, options, workers=2):
        options.validate()
        if bool(options.registrar) != bool(self.registrar) or (self.registrar and self.registrar.key != options.registrar):
            raise ValueError('注册商账户与流程不一致')
        owned = {}
        if self.registrar:
            owned = {r['ym']: nameservers(r.get('ymdns')) for r in self.registrar.all('/api/domain/list')}
            missing = [s.name for s in options.sites if s.name not in owned]
            if missing: raise ValueError('以下域名不在所选 GNAME 账户中：' + ', '.join(missing[:10]))

        def one(site):
            zone = self.zone(site.name, options.account)
            step_names = [('zone', '复用现有 Zone' if zone else '创建 Full Zone')]
            if options.dns_enabled: step_names.append(('dns', '添加或更新 DNS（同名同类型）'))
            if options.settings(): step_names.append(('settings', '应用站点设置'))
            step_names.append(('ns', '将 GNAME NS 切换到 Cloudflare' if self.registrar else '导出 NS，等待手动修改'))
            plans = {}
            if zone:
                for stage in ('dns', 'settings'):
                    if any(s == stage for s, _ in step_names):
                        plans[stage] = self.stage_plan(zone, site, options, stage)
            steps = []
            for stage, summary in step_names:
                body = {'account': options.account}
                if stage == 'dns': body = {'records': options.records(site)}
                elif stage == 'settings': body = options.settings()
                elif stage == 'ns': body = {'registrar': 'GNAME' if self.registrar else '手动', 'name_servers': (zone or {}).get('name_servers', '创建后读取')}
                steps.append(Action(site.name, 'WORKFLOW', stage, body,
                                    summary=summary + ('（创建后生成具体请求）' if not zone and stage in ('dns', 'settings') else '')))
            return site.name, zone, plans, steps
        parts = list(bounded_map(one, options.sites, workers, self.client.cancel))
        by_name = {part[0]: part for part in parts}
        return WorkflowPreview(self.client.key, options,
            [a for site in options.sites for a in by_name[site.name][3]],
            {p[0]: p[1] for p in parts}, {p[0]: p[2] for p in parts}, owned)

    def preview_job(self, options, workers=2):
        snapshot = deepcopy(options)
        return lambda emit: self.preview(snapshot, workers)

    def safe(self, message):
        result = self.client.safe(message)
        return self.registrar.safe(result) if self.registrar else result

    def apply(self, client, plan):
        failures = []
        def collect(aid, state, detail):
            if state in ('失败', '结果未知', '未执行'): failures.append((state, detail))
        # Registrar steps are audited under the explicit workflow's CF owner.
        # Their request uses only the separate registrar client's credentials.
        execute(client, self.store, plan, 1, collect)
        if failures:
            state, detail = failures[0]
            raise ApiError(detail, uncertain=state == '结果未知')

    def run(self, preview, workers, emit):
        options = preview.options
        if preview.owner != self.client.key or (self.registrar.key if self.registrar else '') != options.registrar:
            raise ValueError('此流程属于另一个账户，请重新预览')
        if time.time() - preview.created > 900: raise ValueError('预览已过期，请重新生成')
        self.store.claim_batch(preview.batch)
        for step in preview.steps: self.store.record(step, preview.batch, '等待中')
        def run_site(site):
            steps = [s for s in preview.steps if s.target == site.name]
            failed, zone = False, None
            for step in steps:
                state, detail = '成功', ''
                if failed or self.client.cancel.is_set():
                    state, detail = '未执行', '前序失败或任务取消，请核实远端后重新预览'
                else:
                    self.store.record(step, preview.batch, '执行中')
                    emit(step.id, '执行中', step.summary)
                    try:
                        if step.path == 'zone':
                            current = self.zone(site.name, options.account)
                            before = preview.zones[site.name]
                            if before and (not current or current['id'] != before['id']):
                                raise ValueError('Zone 在预览后发生变化')
                            if not before and current:
                                raise ValueError('预览后出现新 Zone，请重新预览')
                            if current is None:
                                self.apply(self.client, self.provider.plan([], 'zone_add', {'account': options.account, 'names': [site.name]}, 1))
                                current = self.zone(site.name, options.account)
                                if current is None: raise ApiError('创建后暂未读到 Zone，请核实远端后重新预览', uncertain=True)
                            zone = current
                            detail = f"Zone {zone['id']} · 状态 {zone.get('status', '未知')}"
                        elif step.path in ('dns', 'settings'):
                            plan = preview.plans[site.name].get(step.path)
                            if plan is None: plan = self.stage_plan(zone, site, options, step.path)
                            self.apply(self.client, plan)
                            detail = f'{len(plan.actions)} 个请求完成' if plan.actions else '已符合目标配置，无需修改'
                        else:
                            servers = nameservers(zone.get('name_servers'))
                            if len(servers) < 2: raise ValueError('未取得有效 Cloudflare NS，停止修改注册商')
                            if self.registrar:
                                rows = self.registrar.all('/api/domain/list', {'domain': site.name})
                                match = [r for r in rows if r.get('ym') == site.name]
                                if len(match) != 1: raise ValueError('注册商域名归属无法确认')
                                current_ns = nameservers(match[0].get('ymdns'))
                                if current_ns != servers:
                                    if current_ns != preview.registrar_ns[site.name]:
                                        raise ValueError('注册商 NS 在预览后变化，请重新预览')
                                    action = Action(site.name, 'POST', '/api/domain/dns', {'ym': site.name, 'dns': ','.join(servers)}, summary='自动化切换注册商 NS')
                                    self.apply(RegistrarExecutionClient(self.client.key, self.registrar), Plan(self.client.key, [action]))
                                detail = 'NS 已提交/已一致；等待全球生效：' + ', '.join(servers)
                            else:
                                state, detail = '待手动', '请在注册商设置 NS：' + ', '.join(servers)
                    except Exception as exc:
                        state = '未执行' if isinstance(exc, Cancelled) else ('结果未知' if getattr(exc, 'uncertain', False) else '失败')
                        detail, failed = self.safe(exc), True
                self.store.record(step, preview.batch, state, detail)
                emit(step.id, state, detail)
            return True
        try:
            list(bounded_map(run_site, options.sites, workers, self.client.cancel))
        finally:
            for aid in self.store.stop_waiting(preview.batch): emit(aid, '未执行', '调度已停止')

    def execute_job(self, preview, workers=2):
        snapshot = deepcopy(preview)
        return lambda emit: self.run(snapshot, workers, emit)


class RegistrarExecutionClient:
    """Explicit audit-owner adapter; never changes or exchanges HTTP credentials."""
    title = 'GNAME（自动化 NS）'
    def __init__(self, owner, client):
        self.key, self.client, self.cancel = owner, client, client.cancel
    def request(self, method, path, body=None):
        if path != '/api/domain/dns': raise ValueError('此适配器只允许修改 NS')
        return self.client.request(method, path, body)
    def safe(self, message): return self.client.safe(message)
