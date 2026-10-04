"""Application controller: snapshots and use cases, without Qt or widget access."""
from copy import deepcopy
from .execution import execute, bounded_map

class OperationsController:
    def __init__(self, client, store, provider):
        if client.key != store.key:
            raise ValueError('客户端与存储不属于同一个 Token')
        self.client, self.store, self.provider = client, store, provider

    def resolve(self, scope):
        names, selected = scope
        if names:
            return self.provider.resolve(names)
        # Never trust a cached zone ID without re-reading it with the active token.
        return [self.client.get('/zones/' + zone['id']) for zone in selected]

    def preview_job(self, scope, operation, options, workers):
        scope, options = deepcopy(scope), deepcopy(options)
        def run(emit):
            if not emit:
                return self.provider.plan(self.resolve(scope) if scope else [], operation, options, workers)
            def resolve_one(item):
                name = item if isinstance(item, str) else item['name']
                emit('preview:' + name, '读取中', '正在核对域名与权限')
                try:
                    return self.provider.resolve([item])[0] if isinstance(item, str) else self.client.get('/zones/' + item['id'])
                except Exception as exc:
                    emit('preview:' + name, '失败', self.client.safe(exc))
                    raise
            zones = list(bounded_map(resolve_one, scope[0] or scope[1], workers, self.client.cancel)) if scope else []
            return self.provider.plan(zones, operation, options, workers, emit=emit)
        return run

    def inspect_job(self, scope, kind, options, workers):
        scope, options = deepcopy(scope), deepcopy(options)
        return lambda emit: self.provider.inspect(self.resolve(scope), kind, options, workers)

    def execute_job(self, plan, workers):
        plan = deepcopy(plan)
        return lambda emit: execute(self.client, self.store, plan, workers, emit)

    def zones_job(self, emit):
        return self.provider.zones()

    def accounts_job(self, emit):
        return self.client.all('/accounts')
