"""Site workflow planning and optimistic conflict protection; no Qt."""
from copy import deepcopy
from ..models import Action, Plan
from ..execution import execute


def related(rows, site):
    name = site['primary_domain'].removeprefix('*.').lower().rstrip('.')
    return [r for r in rows if r['code'].lower() == site['code'].lower() or
            r['primary_domain'].lower().rstrip('.').removeprefix('*.') == name]


class SiteController:
    def __init__(self, client, store):
        if client.key != store.key: raise ValueError('后台与存储账户不一致')
        self.client, self.store = client, store

    def preview_job(self, sites):
        sites = tuple(sites)
        def run(emit):
            self.client.login()
            rows = self.client.sites()
            actions, skipped = [], []
            for site in sites:
                matches = related(rows, site.body())
                if matches:
                    if len(matches) == 1 and all(matches[0].get(k) == v for k, v in site.body().items()):
                        skipped.append(dict(target=site.code, summary='已存在相同站点', state='已跳过', detail=site.primary_domain))
                        continue
                    raise ValueError(f'{site.code}：已有编码或域名冲突，未覆盖；请先在后台核实')
                actions.append(Action(site.code, 'POST', '/api/sites', site.body(), before=[], guard_path='sites',
                                      summary='创建站点 → ' + site.primary_domain))
            return Plan(self.client.key, actions), skipped
        return run

    def execute_job(self, plan, workers=1):
        snapshot = deepcopy(plan)
        def run(emit):
            if snapshot.owner != self.client.key: raise ValueError('计划属于另一个后台账户')
            self.client.login()
            return execute(self.client, self.store, snapshot, workers, emit,
                read_guard=lambda action: related(self.client.sites(action.target), action.body))
        return run

    def list_job(self, emit):
        self.client.login()
        return self.client.sites()
