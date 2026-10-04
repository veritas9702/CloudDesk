"""Real UI worker/HTTP-mock exercise: progress, no-op explanations and SSL writes."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,time,tempfile,json
from pathlib import Path
from unittest.mock import patch
import httpx
from PySide6.QtWidgets import QApplication,QMessageBox
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
from cloudtool.api_client import Client
from cloudtool.cloudflare import Cloudflare
from cloudtool.storage import Store

class Unlimited:
 def acquire(self,cancel):
  if cancel.is_set():
   from cloudtool.models import Cancelled
   raise Cancelled()
 def defer(self,seconds):pass

app=QApplication([]);configure_app(app)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
settings={};writes=[]
def respond(request):
 time.sleep(.15)
 path=request.url.path.removeprefix('/client/v4')
 if path=='/zones':
  name=request.url.params['name'];result=[{'id':name,'name':name}]
 elif path.endswith('/dns_records'):result=[]
 elif '/settings/' in path:
  key=path.rsplit('/',1)[-1]
  if request.method=='PATCH':
   settings[path]=json.loads(request.content)['value'];writes.append((path,settings[path]))
  result={'id':key,'value':settings.get(path,'auto' if key=='ssl_automatic_mode' else 'off'),'editable':True}
 else:raise AssertionError(path)
 return httpx.Response(200,json={'success':True,'result':result})
with tempfile.TemporaryDirectory() as tmp:
 shell=PlatformWindow(Path(tmp));shell.resize(1440,960);shell.show();app.processEvents()
 w=shell.workspaces['cloudflare'];w.client=Client('fake-token',transport=httpx.MockTransport(respond),global_limiter=Unlimited());w.client.limiter=Unlimited()
 w.store=Store(Path(tmp),w.client.key);w.provider=Cloudflare(w.client,w.store)
 errors=[];w.error=errors.append
 w.scope.setPlainText('example.com\nexample.net\nexample.org')
 w.nav.setCurrentRow(3);w.filters['replace'][0].setText('@,*');w.filters['replace'][2].setText('192.0.2.1');w.replace_new.setText('192.0.2.2')
 seen=[]
 def wait():
  deadline=time.monotonic()+15;last=time.monotonic();gaps=[]
  while w.busy and time.monotonic()<deadline:
   app.processEvents();seen.extend(r['state'] for r in w.plan_model.rows)
   now=time.monotonic();gaps.append(now-last);last=now;time.sleep(.01)
  app.processEvents();assert not w.busy and not errors,errors
  assert max(gaps,default=0)<.5,'UI event loop blocked'
 w.preview();wait()
 assert '读取中' in seen,seen
 assert len(w.plan_model.rows)==3 and not w.plan.actions
 assert all('没有 DNS 记录' in r['detail'] for r in w.plan_model.rows)
 shell.grab().save(str(out/'empty-dns.png'))
 w.set_task_expanded(False);w.nav.setCurrentRow(7)
 value=w.settings_ui['SSL/TLS'][1];value.setCurrentIndex(value.findData('strict'))
 w.preview();wait();assert len(w.plan.actions)==6
 with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):w.execute_plan()
 wait();assert len(writes)==6 and all(r['state']=='成功' for r in w.plan_model.rows)
 assert '成功 6' in w.status.text(),w.status.text()
 shell.grab().save(str(out/'ssl-completed.png'))
 shell.close();app.processEvents()
print('Live worker progress, no-op DNS reasons, responsive event loop and six audited SSL writes passed')
