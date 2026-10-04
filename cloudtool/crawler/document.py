"""Parser based discovery and rewriting. Resolver decides scope and destinations."""
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import tinycss2
import xml.etree.ElementTree as ET


def css_document(text, resolve, lightweight=False):
    tokens = tinycss2.parse_component_value_list(text)

    def string_token(token, target):
        token.value = target
        token.representation = '"' + target.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\a ') + '"'

    def walk(items):
        importing = False
        for token in items:
            if token.type == 'at-keyword':
                importing = token.value.lower() == 'import'
            elif token.type == 'string' and importing:
                string_token(token, resolve(token.value, 'stylesheet'))
                importing = False
            elif token.type == 'url':
                target = resolve(token.value, 'stylesheet' if importing else ('asset' if not lightweight else 'remote'))
                token.value = target
                token.representation = 'url("' + target.replace('\\', '\\\\').replace('"', '\\"') + '")'
                importing = False
            elif token.type == 'function' and token.lower_name == 'url':
                for arg in token.arguments:
                    if arg.type == 'string':
                        string_token(arg, resolve(arg.value, 'stylesheet' if importing else ('asset' if not lightweight else 'remote')))
                importing = False
            elif hasattr(token, 'content'):
                walk(token.content)
            elif hasattr(token, 'arguments'):
                walk(token.arguments)
    walk(tokens)
    return tinycss2.serialize(tokens)


def srcset(text, resolve):
    # A data URL can contain commas; split candidates only after its descriptor.
    result = []
    for match in re.finditer(r'\s*(data:[^\s]+|[^\s,]+)\s*([^,]*)(?:,|$)', text):
        url, descriptor = match.groups()
        result.append(resolve(url, 'asset') + (' ' + descriptor.strip() if descriptor.strip() else ''))
    return ', '.join(result)


def svg_document(data, resolver):
    root = ET.fromstring(data)
    for element in root.iter():
        for key, value in list(element.attrib.items()):
            if key.rsplit('}', 1)[-1] == 'href':
                element.set(key, resolver(value, 'asset'))
            elif key == 'style':
                element.set(key, css_document(value, resolver))
        if element.tag.rsplit('}', 1)[-1] == 'style' and element.text:
            element.text = css_document(element.text, resolver)
    declaration = re.match(br'\s*<\?xml[^>]*encoding=["\']([^"\']+)', data)
    encoding = declaration[1].decode('ascii') if declaration else 'utf-8'
    return ET.tostring(root, encoding=encoding, xml_declaration=bool(declaration))


def html_document(data, base, resolver, rewrite=False, encoding=None, lightweight=False):
    soup = BeautifulSoup(data, 'html.parser', from_encoding=encoding)
    base_tag = soup.find('base', href=True)
    if base_tag:
        base = urljoin(base, base_tag['href'])
    resolve = lambda value, kind: resolver(value, kind, base)
    for tag in soup.find_all(True):
        # HTMLParser lowercases foreign-content attributes; restore SVG spelling.
        if tag.name == 'svg' or tag.find_parent('svg'):
            for lower, mixed in (('viewbox', 'viewBox'), ('preserveaspectratio', 'preserveAspectRatio'), ('gradientunits', 'gradientUnits'), ('gradienttransform', 'gradientTransform'), ('patternunits', 'patternUnits'), ('markerwidth', 'markerWidth'), ('markerheight', 'markerHeight'), ('refx', 'refX'), ('refy', 'refY')):
                if lower in tag.attrs:
                    tag.attrs[mixed] = tag.attrs.pop(lower)
        for attr in ('src', 'poster', 'data-src', 'data-original', 'data-lazy-src'):
            if tag.get(attr):
                kind = 'page' if tag.name in ('iframe', 'frame') else ('remote' if lightweight and tag.name != 'script' else 'asset')
                tag[attr] = resolve(str(tag[attr]), kind)
        for attr in ('srcset', 'data-srcset'):
            if tag.get(attr):
                tag[attr] = srcset(str(tag[attr]), lambda value, kind: resolve(value, 'remote' if lightweight else kind))
        if tag.get('href'):
            kind = 'page' if tag.name in ('a', 'area') else 'asset'
            if tag.name == 'link' and not set(tag.get('rel', [])) & {'stylesheet', 'icon', 'preload', 'modulepreload', 'apple-touch-icon'}:
                kind = 'link'
            if lightweight and kind == 'asset' and not (tag.name == 'link' and
                    (set(tag.get('rel', [])) & {'stylesheet', 'modulepreload'} or tag.get('as') in ('style', 'script'))):
                kind = 'remote'
            if tag.name != 'base':
                if tag.name == 'link' and 'stylesheet' in tag.get('rel', []):
                    kind = 'stylesheet'
                tag['href'] = resolve(str(tag['href']), kind)
        if tag.get('xlink:href'):
            tag['xlink:href'] = resolve(str(tag['xlink:href']), 'remote' if lightweight else 'asset')
        if tag.name == 'object' and tag.get('data'):
            tag['data'] = resolve(str(tag['data']), 'remote' if lightweight else 'asset')
        if tag.get('style'):
            tag['style'] = css_document(str(tag['style']), resolve, lightweight)
        if tag.name == 'style' and tag.string:
            tag.string = css_document(str(tag.string), resolve, lightweight)
        if rewrite:
            if tag.name == 'base':
                tag.decompose()
                continue
            if tag.name == 'meta' and str(tag.get('http-equiv', '')).lower() == 'content-security-policy':
                tag.decompose()
                continue
            # Rewritten CSS no longer matches original integrity hashes.
            tag.attrs.pop('integrity', None)
            if tag.get('action'):
                tag['action'] = urljoin(base, tag['action'])
    if rewrite and not soup.find('meta', charset=True):
        meta = soup.new_tag('meta', charset=soup.original_encoding or encoding or 'utf-8')
        (soup.head or soup).insert(0, meta)
    return soup.encode(soup.original_encoding or encoding or 'utf-8', errors='xmlcharrefreplace')
