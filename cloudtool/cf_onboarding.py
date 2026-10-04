"""Cloudflare-only onboarding, DNS review and registrar export services."""
from copy import deepcopy
from dataclasses import replace
from .automation import OnboardingController, nameservers
from .models import Action, Plan, ApiError, Cancelled, canonical

CACHE = 'cf-onboarding-v1'


def ns_export(rows):
    lines = []
    for row in rows:
        ns = nameservers(row.get('name_servers', []))
        if row.get('id') and len(set(ns)) >= 2:
            lines.append(row['name'] + '|' + ','.join(ns))
    return '\n'.join(dict.fromkeys(lines))


def record_body(record):
    fields = ('type', 'name', 'content', 'ttl', 'priority', 'data', 'proxied', 'comment', 'tags', 'settings')
    return {k: deepcopy(record[k]) for k in fields if k in record}


class CFOnboarding(OnboardingController):
    def preview(self, options, workers=2):
        return super().preview(replace(options, ssl='flexible'), workers)

    def stage_plan(self, zone, site, options, stage):
        if stage == 'settings':
            values = {'ssl_automatic_mode': 'custom', **options.settings()}
            return self.provider.plan([zone], 'settings', {'values': values}, 1)
        return super().stage_plan(zone, site, options, stage)

    def accounts(self):
        warning = ''
        try:
            accounts = self.client.all('/accounts')
        except Cancelled:
            raise
        except ApiError as exc:
            if exc.status != 403:
                raise
            accounts = []
            warning = '账户列表读取受限，当前仅列出已有域名所属账户。'
        if not accounts:
            accounts = [z.get('account', {}) for z in self.client.all('/zones')]
            warning = warning or '账户列表为空，已尝试从已有域名读取所属账户。'
        unique = {a['id']: a for a in accounts if a.get('id')}
        if not unique:
            warning += ' 未读取到可用账户；请核对 Token 的 Account Read 权限和账户范围，或手动填写 Account ID。'
        return list(unique.values()), warning

    def saved(self):
        return self.store.cached(CACHE, [])

    def save_row(self, row):
        rows = self.saved()
        rows = [r for r in rows if (r.get('account'), r['name']) != (row['account'], row['name'])]
        rows.append(deepcopy(row))
        self.store.cache(CACHE, rows)

    def run_onboarding(self, preview, emit):
        # Existing controller guards preview ownership, expiry and remote changes.
        failures = {}
        steps = {s.id: s for s in preview.steps}
        def progress(aid, state, detail):
            if state in ('失败', '结果未知'):
                step = steps[aid]
                failures[step.target] = f'{step.summary}：{detail}'
            emit(aid, state, detail)
        self.run(preview, 2, progress)
        for site in preview.options.sites:
            if self.client.cancel.is_set():
                break
            row = dict(name=site.name, account=preview.options.account, state='读取中', dns='未扫描')
            try:
                zone = self.zone(site.name, preview.options.account)
                if not zone:
                    raise ValueError('创建未成功，请查看任务记录并重新预览')
                row.update(zone, account=preview.options.account)
                row['state'] = '已激活' if zone.get('status') == 'active' else '待更换 NS / 生效'
                self.save_row(row)  # Keep assigned NS even if scanning fails.
                self.trigger(row)
                row['dns'] = '扫描已提交，点击核对 DNS 获取结果'
            except Exception as exc:
                row['detail'] = self.client.safe(exc)
                if not row.get('id'): row['state'] = '失败'
                row['dns'] = '扫描未完成，请重试 / 核对 DNS'
            if site.name in failures:
                row['state'] = '需处理' if row.get('id') else '失败'
                row['detail'] = failures[site.name] + ('；' + row['detail'] if row.get('detail') else '')
            elif row.get('id'):
                row['detail'] = 'SSL 灵活已配置。' + row.get('detail', '')
            self.save_row(row)
        return self.saved()

    def checked_zone(self, row):
        zone = self.client.get('/zones/' + row['id'])
        if zone.get('name') != row['name'] or zone.get('account', {}).get('id') != row['account']:
            raise ValueError('域名所属账户已变化，请重新添加 / 读取')
        return zone

    def write(self, row, suffix, body, summary):
        self.checked_zone(row)
        self.apply(self.client, Plan(self.client.key, [Action(row['name'], 'POST',
            '/zones/' + row['id'] + suffix, body, summary=summary)]))

    def trigger(self, row):
        self.write(row, '/dns_records/scan/trigger', None, '扫描原 DNS（尚未导入）')

    def review(self, row):
        self.checked_zone(row)
        return {'pending': self.client.get('/zones/' + row['id'] + '/dns_records/scan/review') or [],
                'existing': self.client.all('/zones/' + row['id'] + '/dns_records')}

    def accept(self, row, selected):
        if not selected: raise ValueError('请勾选需要导入的记录')
        current = self.review(row)
        pending = {r['id']: r for r in current['pending']}
        for record in selected:
            if pending.get(record.get('id')) != record:
                raise ValueError('扫描记录已变化，请重新核对')
        def identity(record):
            return canonical({k: record.get(k) for k in ('type', 'name', 'content', 'priority', 'data')})
        existing = {identity(r) for r in current['existing']}
        accepted = []
        for record in selected:
            key = identity(record)
            if key not in existing:
                accepted.append(record_body(record))
                existing.add(key)
        if accepted:
            self.write(row, '/dns_records/scan/review', {'accepts': accepted}, '导入已核对的 DNS')
        row = deepcopy(row)
        row['dns'] = f'已导入 {len(accepted)} 条，跳过已有 {len(selected)-len(accepted)} 条；请核对遗漏'
        row['detail'] = ''
        self.save_row(row)
        return self.saved()

    def refresh(self, rows):
        for old in rows:
            if self.client.cancel.is_set(): break
            row = deepcopy(old)
            if not row.get('id'): continue
            try:
                zone = self.checked_zone(row)
                row.update(name_servers=zone.get('name_servers', []), status=zone.get('status'))
                row['state'] = '已激活' if zone.get('status') == 'active' else '待更换 NS / 生效：' + str(zone.get('status'))
                row['detail'] = ''
            except Exception as exc:
                row['detail'] = self.client.safe(exc)
            self.save_row(row)
        return self.saved()
