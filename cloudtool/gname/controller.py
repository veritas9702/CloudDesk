"""GNAME use cases: preview, conflict policy, execution snapshots and auditing."""
from copy import deepcopy
from dataclasses import replace
from ..models import Action, Plan
from ..execution import bounded_map, execute
from .models import domain_lines, domain


class GnameController:
    def __init__(self, client, store):
        if client.key != store.key:
            raise ValueError('GNAME 客户端和存储账户不一致')
        self.client, self.store = client, store

    def domains(self):
        result = self.client.all('/api/domain/list')
        self.store.cache('domains', result)
        return result

    def records(self, name):
        rows = self.client.all('/api/resolution/list', {'ym': name})
        if any('id' not in r or 'zjt' not in r or 'lx' not in r or 'jxz' not in r for r in rows):
            raise ValueError('GNAME 记录字段不完整，已停止')
        return sorted(rows, key=lambda row: str(row['id']))

    def inspect_job(self, text, workers=2):
        names = domain_lines(text)
        def inspect(emit):
            return [row for group in bounded_map(
                lambda name: [dict(r, ym=name) for r in self.records(name)],
                names, workers, self.client.cancel) for row in group]
        return inspect

    def preview_job(self, records, replace_existing=False, workers=2):
        records = tuple(records)
        def preview(emit):
            groups = {}
            for record in records:
                groups.setdefault(record.zone, []).append(record)
            def plan_zone(item):
                name, desired = item
                current = self.records(name)
                deletes, adds = {}, []
                desired_keys = {(r.host, r.kind, r.value, str(r.mx if r.kind == 'MX' else 0)) for r in desired}
                for record in desired:
                    same_host = [r for r in current if str(r['zjt']).lower() == record.host]
                    exact = [r for r in same_host if r['lx'] == record.kind and str(r['jxz']) == record.value
                             and str(r.get('mx', 0)) == str(record.mx if record.kind == 'MX' else 0)
                             and str(r.get('xlid', '0')) in ('', '0')]
                    if exact:
                        continue
                    conflicts = [r for r in same_host if str(r.get('xlid', '0')) in ('', '0')
                                 and (r['lx'] == record.kind or 'CNAME' in (r['lx'], record.kind))]
                    if conflicts and not replace_existing:
                        raise ValueError(f'{name}/{record.host} 已有同名同类型或 CNAME 冲突，请勾选替换后重新预览')
                    for row in conflicts:
                        identity = (str(row['zjt']).lower(), row['lx'], str(row['jxz']), str(row.get('mx', 0)))
                        if identity not in desired_keys:
                            deletes[str(row['id'])] = row
                    adds.append(Action(name, 'POST', '/api/resolution/add', record.body(),
                                       summary=f'添加 {record.host} {record.kind} → {record.value}'))
                actions = [Action(name, 'POST', '/api/resolution/delete', {'ym': name, 'jxid': row['id']},
                                  summary=f"删除冲突 {row['zjt']} {row['lx']} → {row['jxz']}") for row in deletes.values()] + adds
                if actions:
                    actions[0] = replace(actions[0], before=current, guard_path='records', guard_kind='gname')
                return actions
            result = list(bounded_map(plan_zone, groups.items(), workers, self.client.cancel))
            return Plan(self.client.key, [a for group in sorted(result, key=lambda g: g[0].target if g else '') for a in group])
        return preview

    def delete_job(self, text, host, kind, workers=2):
        names = domain_lines(text)
        if not host.strip():
            raise ValueError('删除需要填写精确主机记录，例如 @ 或 www；* 表示通配符主机本身')
        host = host.strip().lower()
        def preview(emit):
            def run(name):
                current = self.records(name)
                actions = [Action(name, 'POST', '/api/resolution/delete', {'ym': name, 'jxid': r['id']},
                                  summary=f"删除 {r['zjt']} {r['lx']} → {r['jxz']}")
                           for r in current if str(r['zjt']).lower() == host and r['lx'] == kind]
                if actions:
                    actions[0] = replace(actions[0], before=current, guard_path='records')
                return actions
            return Plan(self.client.key, [a for group in bounded_map(run, names, workers, self.client.cancel) for a in group])
        return preview

    def ns_job(self, text, nameservers):
        names = domain_lines(text)
        servers = tuple(dict.fromkeys(domain(v) for v in nameservers.replace(',', '\n').splitlines() if v.strip()))
        if not 2 <= len(servers) <= 13:
            raise ValueError('请输入 2–13 个 NS 主机名')
        def preview(emit):
            owned = {r['ym']: r for r in self.domains()}
            if any(n not in owned for n in names):
                raise ValueError('部分域名不在当前 GNAME 账户可见列表中')
            return Plan(self.client.key, [Action(n, 'POST', '/api/domain/dns', {'ym': n, 'dns': ','.join(servers)},
                        summary='修改 NS → ' + ','.join(servers)) for n in names])
        return preview

    def execute_job(self, plan, workers=2):
        snapshot = deepcopy(plan)
        return lambda emit: execute(self.client, self.store, snapshot, workers, emit,
                                    read_guard=lambda action: self.records(action.target))
