"""Acceptance policy; a failed homepage is never a partially completed template."""
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Verdict:
    state: str
    publish: bool
    detail: str


def assess(seed, rows, warnings, size):
    good = [r for r in rows if r['state'] == 'done']
    pages = [r for r in good if r['kind'] == 'page']
    failed = [r for r in rows if r['state'] not in ('done', 'excluded')]
    home = next((r for r in rows if r['url'] == seed), None)
    if not home or home['state'] != 'done' or not pages:
        reason = home.get('error') if home else None
        return Verdict('采集失败', False, '首页未成功保存，不生成模板。' + (reason or '请检查网址和网络后重试'))
    summary = f'{len(pages)} 个页面，{len(good)} 个文件，{size / 1048576:.2f} MB；失败 {len(failed)} 项'
    broken_styles = [r for r in failed if r['kind'] == 'asset' and
                     (r.get('required_style') or urlsplit(r['url']).path.lower().endswith('.css') or 'text/css' in r.get('mime', ''))]
    if broken_styles:
        return Verdict('未通过验收', False, summary + f'。{len(broken_styles)} 项样式文件未保存，页面布局可能损坏，不输出为模板；可重试或清理此任务缓存。' + (broken_styles[0].get('error') or ''))
    if any(r['kind'] == 'asset' for r in failed) and not any(r['kind'] == 'asset' for r in good):
        return Verdict('未通过验收', False, summary + '。引用资源均未保存，不输出为模板；可重试或清理此任务缓存。')
    if any('首页静态内容很少' in warning for warning in warnings):
        return Verdict('未通过验收', False, summary + '。首页是待脚本生成的空壳；断点保留，不输出为模板。')
    incomplete = bool(failed or warnings)
    if incomplete:
        reason = (failed[0].get('error') if failed else warnings[0]) or '有未完成项目'
        return Verdict('部分完成', True, summary + '。' + reason + '；查看报告并重试失败项。')
    return Verdict('已完成', True, summary + '。已完成所选深度内的静态资源采集。')


def html_problem(data):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(data, 'html.parser')
    title = soup.title.get_text(' ', strip=True).lower() if soup.title else ''
    if any(value in title for value in ('technical difficulties', 'access denied', 'just a moment', 'attention required', 'service unavailable')):
        return 'error', '返回的是访问拦截或服务异常页面；请在普通浏览器核实后重试'
    if soup.find('script') and not soup.find(['img', 'svg']) and len(soup.get_text(' ', strip=True)) < 80:
        return 'warning', '首页静态内容很少，可能依赖 JavaScript 生成；请检查预览，当前引擎不执行脚本'
    return '', ''
