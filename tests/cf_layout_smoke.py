import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys,time,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from cloudtool.ui import configure_app
from cloudtool.shell import PlatformWindow
app=QApplication([]);configure_app(app)
out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
 shell=PlatformWindow(Path(tmp));shell.show();w=shell.workspaces['cloudflare']
 for width,height in [(1440,960),(1160,850)]:
  shell.resize(width,height);app.processEvents()
  for i in range(2,13):
   w.nav.setCurrentRow(i);app.processEvents();app.processEvents()
   sc=w.form_scrollers[i-1]
   print(width,i,sc.verticalScrollBar().maximum(),w.inputs_scroll.horizontalScrollBar().maximum())
   if i in (2,3,7,11):shell.grab().save(str(out/f'{width}-{i}.png'))
   assert not w.inputs_scroll.horizontalScrollBar().maximum(),(width,i,'horizontal')
   assert not sc.verticalScrollBar().maximum(),(width,i,'vertical')
 w.nav.setCurrentRow(7)
 setting,value,advanced=w.settings_ui['SSL/TLS']
 assert value.count()==6
 for mode in ('auto','strict','full','flexible','off'):
  value.setCurrentIndex(value.findData(mode));op,options=w.collect()
  assert options['values']==({'ssl_automatic_mode':'auto'} if mode=='auto' else {'ssl_automatic_mode':'custom','ssl':mode})
 shell.close();app.processEvents()
print('All 11 operation pages fit at both sizes; SSL display values map correctly')
