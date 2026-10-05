import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QMessageBox
from cloudtool.crawler.ui import CapturePage
from cloudtool.crawler.repository import Repository
from cloudtool.crawler.models import Settings

APP = QApplication.instance() or QApplication([])

class InteractionTests(unittest.TestCase):
    def test_skip_delete_confirm_and_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('cloudtool.crawler.ui.desktop_directory', return_value=str(root/'desktop')):
                page=CapturePage(root/'state')
                page.initial_future.result(timeout=10)
                page.flush()
            try:
                key=page.controller.create('https://failed.test/',str(root/'out'),Settings())[0]
                repo=Repository(root/'state')
                repo.update_task(key,'采集失败')
                repo.close()
                page.refresh()
                page.domains.setPlainText('https://failed.test/\nhttps://new.test/')
                with patch.object(QMessageBox,'exec',return_value=0), patch.object(QMessageBox,'clickedButton', lambda box: next(b for b in box.buttons() if b.text() == '跳过并移除网址')):
                    self.assertEqual(page.confirm_failed(page.model.rows),[])
                self.assertEqual(page.domains.toPlainText(),'https://new.test/')
                self.assertEqual(len(page.controller.snapshot()),1)
                old=dict(page.model.rows[0])
                page.model.rows[0].update(state='等待',revision=old['revision']+1)
                page.refresh([old])
                self.assertEqual(page.model.rows[0]['state'],'等待')
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.No):
                    page.delete_task(key)
                self.assertEqual(len(page.model.rows),1)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Yes):
                    page.delete_task(key)
                self.assertEqual(page.model.rows,[])
                page.refresh([old])
                self.assertEqual(page.model.rows,[])
                page.delete_future.result(timeout=10); page.flush()
                self.assertEqual(page.controller.snapshot(),[])
            finally:
                if page.delete_future:
                    page.delete_future.result()
                    page.flush()
                page.close()

    def test_preview_click_uses_local_cache_even_with_other_tasks_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('cloudtool.crawler.ui.desktop_directory', return_value=str(root/'desktop')):
                page=CapturePage(root/'state')
                page.initial_future.result(timeout=10)
                page.flush()
            try:
                key=page.controller.create('https://preview.test/',str(root/'out'),Settings())[0]
                repo=Repository(root/'state')
                task=repo.task(key)
                folder=Path(task['work'])
                (folder/'index.html').write_text('<html>Local</html>')
                repo.update_task(key,'未通过验收')
                repo.close()
                page.refresh()
                page.busy=True
                with patch('cloudtool.crawler.ui.QDesktopServices.openUrl',return_value=True) as opened:
                    page.domain_clicked(page.model.index(0,1))
                    self.assertTrue(opened.call_args.args[0].toString().startswith('http://127.0.0.1:'))
                    self.assertEqual(page.controller.preview_directory(key),folder)
                menu, preview, delete=page.make_task_menu(page.model.rows[0])
                self.assertTrue(preview.isEnabled())
                self.assertIn('padding',menu.styleSheet())
                menu.deleteLater()
            finally:
                page.busy=False
                page.close()

    def test_size_filter_checkboxes_and_batch_delete_scope(self):
        from PySide6.QtCore import Qt
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('cloudtool.crawler.ui.desktop_directory', return_value=str(root/'desktop')):
                page=CapturePage(root/'state')
                page.initial_future.result(timeout=10)
                page.flush()
            try:
                ids=page.controller.create('https://small.test/\nhttps://large.test/\nhttps://boundary.test/',str(root/'out'),Settings())
                repo=Repository(root/'state')
                for key in ids:
                    repo.update_task(key,'已暂停')
                repo.close()
                rows=page.controller.snapshot()
                sizes=dict(zip(ids,[299,1001,1000]))
                for row in rows: row['template_bytes']=sizes[row['id']]*1048576
                page.refresh(rows)
                page.size_limit.setValue(1)
                self.assertEqual(page.size_limit.value(),300)
                page.size_limit.setValue(1000)
                page.size_filter.setChecked(True)
                self.assertEqual([r['id'] for r in page.visible_rows()],[ids[1]])
                page.check_visible(True)
                self.assertEqual(page.model.checked,{ids[1]})
                page.size_limit.setValue(2000)
                self.assertEqual(page.model.checked,set())
                page.size_limit.setValue(1000)
                index=page.model.index(page.row_indexes[ids[1]],0)
                page.model.setData(index,Qt.CheckState.Checked,Qt.ItemDataRole.CheckStateRole)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.No):
                    page.delete_checked()
                self.assertEqual(len(page.controller.snapshot()),3)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Yes):
                    page.delete_filtered()
                page.delete_future.result();page.flush()
                self.assertEqual({r['id'] for r in page.controller.snapshot()},{ids[0],ids[2]})
            finally:
                if page.delete_future:
                    page.delete_future.result();page.flush()
                page.close()

    def test_failed_filter_and_delete_all_failed_preserve_other_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('cloudtool.crawler.ui.desktop_directory', return_value=str(root/'desktop')):
                page=CapturePage(root/'state')
                page.initial_future.result(timeout=10)
                page.flush()
            try:
                ids=page.controller.create('\n'.join(f'https://site{i}.test/' for i in range(5)),str(root/'out'),Settings())
                repo=Repository(root/'state')
                states=['采集失败','未通过验收','部分完成','已完成','采集中']
                folders=[]
                for key,state in zip(ids,states):
                    folder=Path(repo.task(key)['work']);(folder/'index.html').write_text('test')
                    folders.append(folder);repo.update_task(key,state)
                repo.close();page.refresh()
                page.state_filter.setCurrentText('失败任务')
                self.assertEqual({r['id'] for r in page.visible_rows()},set(ids[:2]))
                self.assertTrue(page.delete_filtered_button.isEnabled())
                page.check_visible(True);self.assertEqual(page.model.checked,set(ids[:2]))
                page.state_filter.setCurrentText('已完成')
                self.assertFalse(page.model.checked)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.No):page.delete_failed()
                self.assertEqual(len(page.controller.snapshot()),5)
                with patch.object(QMessageBox,'exec',return_value=QMessageBox.StandardButton.Yes):page.delete_failed()
                page.delete_future.result();page.flush()
                self.assertEqual({r['id'] for r in page.controller.snapshot()},set(ids[2:]))
                self.assertFalse(any(f.exists() for f in folders[:2]))
                self.assertTrue(all(f.exists() for f in folders[2:]))
            finally:
                if page.delete_future:page.delete_future.result();page.flush()
                page.close()

    def test_automatic_homepage_cleanup_updates_list_and_input(self):
        import json
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('cloudtool.crawler.ui.desktop_directory', return_value=str(root/'desktop')):
                page=CapturePage(root/'state')
                page.initial_future.result(timeout=10)
                page.flush()
            try:
                key=page.controller.create('https://missing.test/',str(root/'out'),Settings())[0]
                page.refresh()
                page.domains.setPlainText('https://missing.test/\nhttps://keep.test/')
                row=dict(page.model.rows[0],state='已自动清理',deleted=1,revision=100)
                page.worker=Mock()
                page.worker.take_events.return_value={key:('已自动清理',json.dumps(dict(task=row,detail='已清理')))}
                page.flush()
                self.assertEqual(page.model.rows,[])
                self.assertEqual(page.domains.toPlainText(),'https://keep.test/')
            finally:
                page.worker=None
                page.close()
