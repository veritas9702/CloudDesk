"""BUTTON / searchable INPUT / BUTTON regression matching the supplied diagnostic."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,Error
from tools.generate_extension import catalog
root=Path(__file__).resolve().parents[1]
from browser_fixtures import html
with sync_playwright() as engine:
 browser=engine.chromium.launch(channel='chrome',headless=True)
 page=browser.new_page();page.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
 def load():
  page.goto('https://dash.cloudflare.com/profile/api-tokens')
  for f in ('catalog.js','form.js'):page.add_script_tag(content=(root/'browser_extension'/f).read_text('utf-8-sig'))
 load()
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 assert page.evaluate('searches')>=12
 assert page.evaluate('chosen')>=25
 assert page.evaluate('submitted')==0
 assert page.locator('#ip').input_value()=='192.0.2.1'
 # Typing the target without committing must never satisfy verification.
 page.locator('.row').first.locator('span').evaluate("e=>e.textContent='错误权限'")
 page.locator('.row').first.locator('input').fill('DNS')
 try:page.evaluate('CloudDeskForm.verify(CloudDeskCatalog.full)');raise AssertionError('search text accepted as selected permission')
 except Error:pass
 # Also exercise localized permission lookup after English has no match.
 load()
 page.evaluate("NAMES.splice(0,NAMES.length,'区域','区域设置','清除缓存','DNS','SSL 和证书','页面规则')")
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.basic)')==6
 # Actual user diagnostic: selected name is only an INPUT value, no sibling label.
 original=html
 html=original.replace("selected.textContent='区域'", "selected.textContent=''").replace("const input=document.createElement('input');", "const input=document.createElement('input');input.value='区域';").replace("selected.textContent=n;input.value='';", "selected.textContent='';input.value=n;")
 load()
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 assert page.locator('.row input').first.input_value()=='DNS'
 # Re-running completed input-value forms must reselect and verify without duplicates.
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 assert page.locator('.row').count()==13
 # A typed search word is not proof even on input-only controls.
 page.locator('.row input').first.fill('DNS')
 try:page.evaluate('CloudDeskForm.verify(CloudDeskCatalog.full)');raise AssertionError('uncommitted query accepted')
 except Error:pass
 # Empty permission/level and placeholder scope still identify a permission row.
 html=html.replace("input.value='区域'", "input.value=''").replace("['区域','账户'],'区域'", "['区域','账户'],'选择...'").replace("['读取','编辑','清除'],'读取'", "['读取','编辑','清除'],'选择...'")
 load()
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 # Cancel after partially filling, then resume with no duplicate rows.
 load()
 try:page.evaluate("CloudDeskForm.fill(CloudDeskCatalog.full,()=>{},()=>document.querySelectorAll('.row').length>=4)");raise AssertionError('cancel ignored')
 except Error:pass
 assert page.locator('.row').count()==4
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 assert page.locator('.row').count()==13
 # Extra rows are never silently deleted or submitted.
 page.evaluate('add()')
 try:page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)');raise AssertionError('extra permissions accepted')
 except Error:pass
 assert page.locator('.row').count()==14
 assert page.evaluate('submitted')==0
 assert page.locator('#ip').input_value()=='192.0.2.1'
 browser.close()
print('PASS: searchable permission input, pointer-driven buttons, Chinese aliases, committed-label verification; no submission/IP changes')
