"""Map public URL paths to safe Windows files without flattening the website."""
import re
from hashlib import sha256
from pathlib import PurePosixPath
from urllib.parse import urlsplit, unquote


def segment(value):
    decoded = unquote(value)
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', decoded).rstrip(' .')
    reserved = re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', clean, re.I)
    if not clean or clean in ('.', '..') or reserved or clean != decoded or len(clean) > 80:
        clean = (clean[:60] or 'file') + '~' + sha256(value.encode()).hexdigest()[:12]
    return clean


def original_path(url, kind, seed):
    parsed = urlsplit(url)
    parts = [segment(p) for p in parsed.path.split('/') if p]
    if not parts or parsed.path.endswith('/'):
        parts.append('index.html' if kind == 'page' else 'resource')
    elif kind == 'page':
        suffix = PurePosixPath(parts[-1]).suffix.lower()
        if not suffix:
            parts.append('index.html')
        elif suffix not in ('.html', '.htm', '.shtml'):
            parts[-1] += '.html'
    if parsed.query:
        path = PurePosixPath(parts[-1])
        parts[-1] = path.stem + '~q-' + sha256(parsed.query.encode()).hexdigest()[:12] + path.suffix
    if parsed.netloc.lower() != urlsplit(seed).netloc.lower():
        parts = ['_external', segment(parsed.netloc), *parts]
    result = '/'.join(parts)
    if len(result) > 170:
        result = '_long/' + sha256(url.encode()).hexdigest()[:24] + PurePosixPath(result).suffix
    return result


def unique_path(path, url, occupied, directories):
    """Windows is case insensitive; handle file/directory and escaped-name collisions."""
    candidate = path
    for attempt in range(100):
        folded = candidate.casefold()
        ancestors = [str(p).casefold() for p in PurePosixPath(candidate).parents if str(p) != '.']
        if folded not in occupied and folded not in directories and not any(p in occupied for p in ancestors):
            return candidate
        original = PurePosixPath(path)
        # Separate namespace also resolves an ancestor that is already a file.
        candidate = '_conflicts/' + sha256((url + str(attempt)).encode()).hexdigest()[:20] + '/' + original.name
    raise ValueError('无法分配不冲突的本地文件路径')
