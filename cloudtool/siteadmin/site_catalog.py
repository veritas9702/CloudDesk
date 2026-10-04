"""Read-only site inventory and domain import/export policy; independent of Qt."""
import json
from ..domain_names import domain
from ..execution import bounded_map
from ..models import Cancelled
from .models import Site


def site_domain(row):
    value=row.get('primary_domain','')
    if not isinstance(value,str):raise ValueError('主域名缺失')
    return domain(value.strip().removeprefix('*.'))


def site_visit_url(row):
    name = site_domain(row)
    protocol = row.get('link_protocol', 'https')
    if protocol not in ('https', 'http'):
        raise ValueError('站点访问协议无效')
    host = name if name.startswith('www.') else 'www.' + name
    return f'{protocol}://{host}/'


def domain_lines(rows):
    names=[];seen=set();invalid=0
    for row in rows:
        try:name=site_domain(row)
        except ValueError:invalid+=1;continue
        if name not in seen:names.append(name);seen.add(name)
    return '\n'.join(names),invalid


def imported_sites(rows):
    mapping={};duplicates=set()
    for row in rows:
        try:name=site_domain(row)
        except ValueError:continue
        if name in mapping:duplicates.add(name)
        mapping[name]=Site(**{k:row[k] for k in ('code','name','primary_domain','link_protocol')})
    for name in duplicates:mapping.pop(name,None)
    return mapping


class SiteCatalog:
    def __init__(self,client):self.client=client

    def list_job(self,emit):
        self.client.login();rows=self.client.sites()
        for row in rows:
            row.update(publication='核对中',publication_detail='')
            emit('@site:'+str(row['id']),'核对中',json.dumps(row,ensure_ascii=False))
        def check(row):
            try:row['publication']=self.client.publication(row['id'])
            except Cancelled:raise
            except Exception as exc:
                row.update(publication='待核实',publication_detail=self.client.safe(exc))
            return row
        for count,row in enumerate(bounded_map(check,rows,2,self.client.cancel),1):
            emit('@site:'+str(row['id']),row['publication'],json.dumps(row,ensure_ascii=False))
            emit('@request','核对发布',f'发布状态 {count}/{len(rows)} · {row["code"]}：{row["publication"]}')
        return rows
