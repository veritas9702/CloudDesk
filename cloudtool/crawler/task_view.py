"""Shared task ordering, counting and retry policy, without Qt or I/O."""
FAILED = {'删除失败', '采集失败', '未通过验收', '需检查目录', '已清理'}
ACTIVE = {'采集中', '整理中'}
RANK = {'等待': 0, '采集中': 1, '整理中': 1, '已暂停': 2,
        '采集失败': 3, '未通过验收': 3, '需检查目录': 3, '已清理': 3,
        '部分完成': 4, '已完成': 5}


def ordered(rows):
    # Stable sort: newest end time first within each state group.
    result = sorted(rows, key=lambda r: (r.get('ended_at') or r.get('created') or '', r['id']), reverse=True)
    return sorted(result, key=lambda r: RANK.get(r['state'], 3))


def summary(rows):
    return dict(total=len(rows), waiting=sum(r['state'] == '等待' for r in rows),
                running=sum(r['state'] in ACTIVE for r in rows),
                paused=sum(r['state'] == '已暂停' for r in rows),
                failed=sum(r['state'] in FAILED for r in rows),
                partial=sum(r['state'] == '部分完成' for r in rows),
                completed=sum(r['state'] == '已完成' for r in rows))


def urls_for(rows):
    return {url for r in rows for url in [r['seed'], *r.get('aliases', [])]}
