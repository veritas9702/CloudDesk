"""Check the two-step dialog without opening a real user browser."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys,tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
from cloudtool.ui import configure_app
from cloudtool.browser_token_ui import BrowserTokenDialog
app=QApplication([]);configure_app(app)
output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=True)
calls=[]
with tempfile.TemporaryDirectory() as root:
 d=BrowserTokenDialog(root,launcher=lambda *args:calls.append(args))
 d.show();app.processEvents()
 assert not d.open_button.isEnabled()
 d.open_install()
 assert calls[-1]==('chrome','chrome://extensions/')
 assert Path(d.path.text(),'manifest.json').exists()
 assert QApplication.clipboard().text()==d.path.text()
 assert not d.open_button.isEnabled()
 d.installed.setChecked(True);d.open_form()
 assert calls[-1][0]=='chrome' and 'clouddesk_setup=full' in calls[-1][1]
 d.browser.setCurrentIndex(1)
 assert not d.open_button.isEnabled()
 d.open_install();assert calls[-1]==('msedge','edge://extensions/')
 d.browser.setCurrentIndex(0);app.processEvents()
 for widget in (d.install,d.path,d.installed,d.permission_mode,d.open_button):
  assert widget.isVisible() and widget.width()>100
 d.grab().save(str(output/'permission-helper.png'))
 d.close()
print('PASS: preparation does not claim installed; Chrome / Edge remain explicit; setup confirmation resets on browser change')
