"""Real Chrome executes extension JS against an offline form; no account involved."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,Error
from tools.generate_extension import catalog
names=sorted({r['names'][0] for r in catalog()['full']})
html='''<html><body><section><div id="rows"></div><button onclick="add()">Add more</button></section>
<section><input id="ip" value="192.0.2.1"><button>Add more</button></section>
<button onclick="window.submitted++">Continue to summary</button>
<script>window.submitted=0;const NAMES=__NAMES__;
function add(){let e=document.createElement('div');e.innerHTML='<select><option>Zone</option><option>Account</option></select><select>'+NAMES.map(n=>'<option>'+n+'</option>').join('')+'</select><select><option>Read</option><option>Edit</option><option>Purge</option></select>';document.querySelector('#rows').append(e);e.children[1].value='Zone';}add();</script></body></html>'''.replace('__NAMES__',json.dumps(names))
root=Path(__file__).resolve().parents[1]
with sync_playwright() as engine:
 browser=engine.chromium.launch(channel='chrome',headless=True)
 page=browser.new_page()
 page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
 def load(url='https://dash.cloudflare.com/profile/api-tokens'):
  page.goto(url)
  for filename in ('catalog.js','form.js'):page.add_script_tag(content=(root/'browser_extension'/filename).read_text('utf-8'))
 load()
 page.evaluate('''() => {window.scopeChanges=0;document.querySelector('#rows select').addEventListener('change',()=>{window.scopeChanges++;document.querySelectorAll('#rows select')[2].selectedIndex=-1;});}''')
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)')==13
 assert page.evaluate('window.scopeChanges')==0
 assert page.evaluate('window.submitted')==0
 assert page.locator('#ip').input_value()=='192.0.2.1'
 diagnostic=page.evaluate('JSON.stringify(CloudDeskForm.diagnostics())')
 assert '192.0.2.1' not in diagnostic and 'profile/api-tokens' not in diagnostic
 page.locator('#rows select').nth(2).select_option('Read')
 try:page.evaluate('CloudDeskForm.verify(CloudDeskCatalog.full)');raise AssertionError('tamper accepted')
 except Error:pass
 load('https://example.com/profile/api-tokens')
 try:page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full)');raise AssertionError('origin accepted')
 except Error:pass
 load()
 try:page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.full,()=>{},()=>true)');raise AssertionError('cancel ignored')
 except Error:pass
 assert page.locator('#rows > div').count()==1
 load()
 assert page.evaluate('CloudDeskForm.fill(CloudDeskCatalog.basic)')==6
 load('https://dash.cloudflare.com/profile/api-tokens?clouddesk_setup=full')
 page.add_script_tag(content=(root/'browser_extension/assistant.js').read_text('utf-8'))
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')")
 assert page.evaluate('window.submitted')==0
 browser.close()
print('PASS: extension JS fills 13 advanced / 6 basic permissions; no submit, IP unchanged; tamper/origin/cancel rejected')
