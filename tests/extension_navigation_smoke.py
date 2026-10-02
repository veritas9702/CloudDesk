"""Reproduce URL cleanup before DOM ready and clean-URL popup recovery."""
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[1]
# Reuse the realistic permission names and offline native fixture.
from tools.generate_extension import catalog
import json
names=sorted({r['names'][0] for r in catalog()['full']})
html='''<html><head><script>history.replaceState({},'',location.pathname);</script></head><body>
<section><div id="rows"></div><button onclick="add()">Add more</button></section>
<input id="ip" value="192.0.2.1"><button onclick="window.submitted++">Create token</button>
<script>window.submitted=0;const NAMES=__NAMES__;
function add(){let e=document.createElement('div');e.innerHTML='<select><option>Zone</option><option>Account</option></select><select>'+NAMES.map(n=>'<option>'+n+'</option>').join('')+'</select><select><option>Read</option><option>Edit</option><option>Purge</option></select>';document.querySelector('#rows').append(e);e.children[1].value='Zone';}
setTimeout(add,300);</script></body></html>'''.replace('__NAMES__',json.dumps(names))
script="globalThis.chrome={runtime:{onMessage:{addListener(fn){globalThis.receive=fn;}}}};\n"+'\n'.join((root/'browser_extension'/name).read_text('utf-8-sig') for name in ('catalog.js','form.js','assistant.js','bridge.js'))
with sync_playwright() as engine:
 browser=engine.chromium.launch(channel='chrome',headless=True)
 page=browser.new_page();page.add_init_script(script=script)
 page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=html))
 page.goto('https://dash.cloudflare.com/profile/api-tokens?clouddesk_setup=full')
 assert '?' not in page.url
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')")
 assert page.evaluate('submitted')==0
 assert page.locator('#ip').input_value()=='192.0.2.1'
 # No intent on normal page; explicitly asking the popup starts it without URL markers.
 page.goto('https://dash.cloudflare.com/profile/api-tokens')
 page.wait_for_timeout(400)
 assert page.locator('#clouddesk-assistant').count()==0
 result=page.evaluate("new Promise(resolve=>receive({type:'clouddesk-fill',mode:'full'},null,resolve))")
 assert result['ok']
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')")
 assert page.locator('#rows > div').count()==13
 # Retry completed form does not duplicate rows.
 page.evaluate("receive({type:'clouddesk-fill',mode:'full'},null,()=>{})")
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')")
 assert page.locator('#rows > div').count()==13
 # Login-to-clean-URL navigation retains only the short-lived mode.
 page.goto('https://dash.cloudflare.com/login?redirect_uri=%2Fprofile%2Fapi-tokens%3Fclouddesk_setup%3Dfull')
 page.goto('https://dash.cloudflare.com/profile/api-tokens')
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')")
 assert page.evaluate('sessionStorage.getItem("clouddesk.pending-permissions.v1")') is None
 assert page.evaluate('submitted')==0
 # Unsupported controls must produce a visible failure, not silently poll forever.
 page.unroute('**/*')
 page.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body='<html><body>Unrecognized form</body></html>'))
 page.goto('https://dash.cloudflare.com/profile/api-tokens?clouddesk_setup=full')
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('助手已启动')")
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('未识别到权限表单')",timeout=18000)
 assert page.evaluate('sessionStorage.getItem("clouddesk.pending-permissions.v1")') is None
 browser.close()
print('PASS: early URL removal, login navigation, clean URL popup retry, duplicate prevention and intent cleanup')
