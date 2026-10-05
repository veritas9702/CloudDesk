"""Conservative classification for automatic template replacement."""
def template_failure(stage, state, detail):
    if state != '失败' or stage not in ('pack','upload','sync','scan','h1','placeholder'):
        return False
    text = str(detail).lower()
    if any(word in text for word in ('timeout','超时','权限','permission','http 401','http 403','http 429','http 50','磁盘','disk','结果未知')):
        return False
    return any(word in text for word in ('未找到 <body>', '缺少 <body>', '未发现 html 页面',
        '扩展名为 html，实际为', '空模板目录', '编码错误', '压缩包超过', '模板解压体积超过', '模板文件数超过'))

