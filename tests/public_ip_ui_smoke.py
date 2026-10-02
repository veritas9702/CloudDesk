import os,tempfile,time,sys
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from cloudtool.ui import configure_app
from cloudtool.browser_token_ui import BrowserTokenDialog
from cloudtool.models import Cancelled
class Service:
 fail=False
 def detect(self,cancel):
  for _ in range(30):
   if cancel.wait(.01):raise Cancelled()
  if self.fail:raise RuntimeError('test error')
  return '8.8.8.8'
app=QApplication([]);configure_app(app)
service=Service();beats=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:beats.append(1));timer.start()
with tempfile.TemporaryDirectory() as root:
 d=BrowserTokenDialog(root,ip_service=service);d.show();app.processEvents();ip=d.ip_widget
 def drain():
  until=time.monotonic()+4
  while ip.job is not None and time.monotonic()<until:app.processEvents();time.sleep(.002)
  assert ip.job is None
 ip.detect();job=ip.job;ip.detect();assert ip.job is job
 drain();assert ip.ip.text()=='8.8.8.8' and len(beats)>10
 ip.copy_ip();assert QApplication.clipboard().text()=='8.8.8.8'
 service.fail=True;ip.detect();assert ip.ip.text()=='' and not ip.copy_button.isEnabled()
 drain();assert '失败' in ip.status.text() and not ip.copy_button.isEnabled()
 service.fail=False;ip.detect();d.reject();drain();assert not d.isVisible()
print('PASS: new-dialog IP detection/copy, failure clears stale IP, no duplicate jobs, responsive UI, safe close')
