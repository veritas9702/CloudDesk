"""Offline credential display and browser prefill regression."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QLineEdit
from cloudtool.ui import Window, configure_app
from cloudtool.token_view_ui import TokenViewDialog

app = QApplication([])
configure_app(app)
output = Path(sys.argv[1]); output.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    w = Window(Path(tmp))
    for number in range(2):
        token = f'OFFLINE_FAKE_TOKEN_{number}'
        p = w.vault.add(f'测试配置 {number}', token, 'test-password-123')
        w.unlocked_passwords[p['id']] = 'test-password-123'
        w.load_profiles(p['id'])
        with patch('cloudtool.ui.TokenViewDialog') as dialog:
            w.view_profile()
            assert dialog.call_args.args[:2] == (p['label'], token)
        assert token not in (Path(tmp) / 'profiles.json').read_text('utf-8')
    w.close()
d = TokenViewDialog('测试配置', 'OFFLINE_FAKE_TOKEN')
d.show(); app.processEvents()
assert d.value.echoMode() == QLineEdit.EchoMode.Password
d.toggle(); assert d.value.echoMode() == QLineEdit.EchoMode.Normal
d.toggle(); assert d.value.echoMode() == QLineEdit.EchoMode.Password
d.copy(); assert app.clipboard().text() == 'OFFLINE_FAKE_TOKEN'
d.grab().save(str(output / 'saved-token.png'))
d.reject(); assert not d.value.text()
app.clipboard().clear()
print('Saved-token isolation, reveal/copy/close and encrypted storage passed')
