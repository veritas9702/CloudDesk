"""SSM processing contracts, reusing the authenticated client and rate limiter."""
from ..models import ApiError

STAGES = ('tdk', 'convert', 'stat_clean', 'link', 'h1', 'placeholder', 'publish')
TITLES = ('TDK 全站替换', '简繁转换', '统计代码清理', '外链替换', 'H1 注入', '占位符注入', '发布上线')


class PipelineAPI:
    def __init__(self, client):
        self.client = client

    def read_post(self, path, body):
        try:
            data = self.client._request('POST', path, body)
        except ApiError as exc:
            # Generation/detection/previews never modify the work directory.
            raise ApiError(str(exc), exc.status) from None
        if not isinstance(data, dict): raise ValueError('后台预览响应格式异常')
        return data

    def generate(self):
        data = self.read_post('/api/tdk/lexicon/generate', {'tk_count':5, 'description_count':8})
        if any(not isinstance(data.get(k), str) or not data[k].strip() for k in ('title','description','keywords')):
            raise ValueError('词库未生成完整 TDK，请检查后台词库')
        return {k:data[k] for k in ('title','description','keywords')}

    def paged(self, path, params=None):
        rows, seen = [], set()
        for page in range(1, 10001):
            data = self.client._request('GET', path, params=dict(params or {}, page=page, size=200), timeout=15)
            if not isinstance(data, dict) or not isinstance(data.get('list'), list) or type(data.get('total')) is not int:
                raise ValueError('后台分页响应异常')
            for row in data['list']:
                if not isinstance(row, dict) or not row.get('id') or row['id'] in seen:
                    raise ValueError('后台分页重复或缺少 ID')
                rows.append(row); seen.add(row['id'])
            if len(rows) >= data['total']: return rows
            if not data['list']: raise ValueError('后台分页提前结束')
        raise ValueError('后台分页超过上限')

    def prepare(self, stage, body, report, expected_total=None):
        if stage == 'tdk': return body, '使用已保存的站点专属 TDK'
        if stage == 'publish':
            # Backend preview ensures scripts in work; call only during execution,
            # after all processing checkpoints, never during the initial plan.
            data = self.client._request('POST', '/api/publish/preview', body)
            digest = data.get('expect_digest') if isinstance(data, dict) else None
            diff = data.get('diff') if isinstance(data, dict) else None
            if (not isinstance(digest, str) or not digest.strip() or not isinstance(diff, dict)
                    or diff.get('digest') != digest
                    or any(type(diff.get(k)) is not int or diff[k] < 0 for k in ('added','modified','deleted','unchanged'))):
                raise ValueError('发布预检缺少有效版本摘要或文件统计，未提交发布')
            if diff['added'] + diff['modified'] + diff['unchanged'] <= 0:
                raise ValueError('工作副本为空，未提交发布')
            return dict(body, expect_digest=digest), f"发布预检通过：新增 {diff['added']}、修改 {diff['modified']}、删除 {diff['deleted']} 个文件"
        if stage == 'stat_clean':
            paths = body.get('rel_paths')
            if not paths:
                pages = self.paged(f"/api/sites/{body['site_id']}/pages")
                if not pages: raise ValueError('扫描结果为空，不能清理统计代码')
                paths = [r.get('rel_path') for r in pages]
                if expected_total is not None and len(paths)!=expected_total:
                    raise ValueError('页面索引与 TDK 已处理文件数不一致，请在后台补齐扫描后恢复，避免漏清理')
            if any(not isinstance(p, str) or not p for p in paths) or len(set(paths)) != len(paths):
                raise ValueError('扫描页面路径缺失或重复')
            selected, review = [], 0
            # Bound each synchronous detection call; no request per HTML file.
            for offset in range(0, len(paths), 100):
                batch = paths[offset:offset+100]
                report(f'检测统计代码 {offset}/{len(paths)}')
                data = self.read_post('/api/stat/detect', dict(site_id=body['site_id'], rel_paths=batch, limit=len(batch)))
                files = data.get('files')
                if not isinstance(files, list) or {r.get('rel_path') for r in files} != set(batch):
                    raise ValueError('统计代码检测未覆盖请求的全部页面')
                for row in files:
                    if row.get('error'): raise ValueError(f"{row['rel_path']}：{row['error']}")
                    if row.get('deletable', 0) > 0: selected.append(row['rel_path'])
                    review += row.get('review', 0)
            return dict(body, rel_paths=selected, include_review=False), f'可安全清理 {len(selected)} 个文件；保留需复核片段 {review} 处'
        data = self.read_post(f'/api/{stage}/preview', dict(body, sample=20, dry_run=True))
        if type(data.get('files')) is not int or data['files'] <= 0 or type(data.get('failed')) is not int:
            raise ValueError('抽样预览未返回有效页面统计')
        if data['failed']:
            errors = [str(r.get('message', '')) for r in data.get('results', []) if r.get('message')]
            raise ValueError(f"抽样预览失败 {data['failed']} 个文件："+'；'.join(errors[:3]))
        return body, f"抽样 {data['files']} 个文件，通过；随后处理全站"

    def submit(self, stage, body):
        if stage not in STAGES: raise ValueError('无效加工步骤')
        path = '/api/stat/clean' if stage == 'stat_clean' else f'/api/{stage}/apply'
        data = self.client._request('POST', path, {**body,'async':True})
        if not isinstance(data, dict) or type(data.get('task_id')) is not int or data['task_id'] <= 0 or data.get('async') is not True:
            raise ApiError('后台没有返回异步任务 ID，请核实任务中心，不能重复提交', uncertain=True)
        return data['task_id']

    def task(self, task_id, site_id, stage):
        data = self.client._request('GET', f'/api/tasks/{task_id}', timeout=15)
        task = data.get('task') if isinstance(data, dict) else None
        if not isinstance(task, dict) or task.get('id') != task_id or task.get('site_id') != site_id or task.get('type') != stage:
            raise ValueError('后台任务身份不匹配，已停止等待，未重复提交')
        return task
