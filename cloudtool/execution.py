"""Bounded scheduling, optimistic guards and audited execution."""
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import Callable
from .models import Cancelled, canonical

def bounded_map(fn: Callable, values, workers, cancel):
    """At most 2*workers futures; no unbounded submission for large imports."""
    values = iter(values)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = set()
        exhausted = False
        while pending or not exhausted:
            if cancel.is_set():
                for f in pending:
                    f.cancel()
                raise Cancelled("任务已取消；已发送的请求可能已经生效")
            while not exhausted and len(pending) < workers * 2:
                try:
                    item = next(values)
                except StopIteration:
                    exhausted = True
                    break
                pending.add(pool.submit(fn, item))
            if not pending:
                break
            done, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                yield future.result()


def execute(client, store, plan, workers, emit, read_guard=None):
    if client.key != plan.owner or store.key != plan.owner:
        raise ValueError("计划属于另一个 Token，禁止执行")
    if time.time() - plan.created > 900:
        raise ValueError("计划已超过 15 分钟，请重新预览")
    store.claim_batch(plan.batch)
    groups = {}
    for a in plan.actions:
        store.record(a, plan.batch, "等待中")
        groups.setdefault(a.target, []).append(a)

    def run(actions):
        blocked = False
        blocked_reason = ''
        for a in actions:
            state, detail = "成功", "已完成"
            if blocked or client.cancel.is_set():
                state, detail = "未执行", ("本域名已停止后续步骤：" + blocked_reason + "；其他域名独立继续处理" if blocked else "任务已取消")
            else:
                try:
                    if a.guard_path:
                        if read_guard is not None:
                            current = read_guard(a)
                        elif a.guard_kind == "dns_batch":
                            wanted = {r["id"] for r in a.before}
                            current = sorted([r for r in client.all(a.guard_path, per_page=1000) if r["id"] in wanted], key=lambda r: r["id"])
                        else:
                            current = client.get(a.guard_path)
                        if canonical(current) != canonical(a.before):
                            raise ValueError("远端内容在预览后已变化，请重新预览")
                    if client.cancel.is_set():
                        raise Cancelled()
                    store.record(a, plan.batch, "执行中")
                    emit(a.id, "执行中", "正在请求 " + getattr(client, "title", "Cloudflare"))
                    result = client.request(a.method, a.path, a.body).get("result")
                    detail = client.safe(canonical(result))
                except Cancelled:
                    state, detail, blocked = "未执行", "任务已取消", True
                except Exception as exc:
                    state = "结果未知" if getattr(exc, "uncertain", False) else "失败"
                    detail, blocked = client.safe(exc), True
            if state in ("失败", "结果未知"):
                blocked_reason = a.summary + "：" + detail
            store.record(a, plan.batch, state, detail)
            emit(a.id, state, detail)
        return True

    try:
        list(bounded_map(run, groups.values(), workers, client.cancel))
    finally:
        # Mark work that was never submitted when cancellation stopped the producer.
        for aid in store.stop_waiting(plan.batch):
            emit(aid, "未执行", "调度已停止")
