"""Exercise the manifest's real MAIN/ISOLATED split using Chrome execution worlds."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
from browser_fixtures import html
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'browser_extension/manifest.json').read_text('utf-8'))
assert manifest['content_scripts'][0]['world']=='MAIN'
assert manifest['content_scripts'][1]['world']=='ISOLATED'
# Model a page-side event/type guard; isolated constructors are not page constructors.
html=html.replace("input.oninput=()=>{", "input.oninput=(event)=>{if(!(event instanceof InputEvent)){input.value='区域';return;}")
with sync_playwright() as engine:
 browser=engine.chromium.launch(channel='chrome',headless=True)
 page=browser.new_page();cdp=page.context.new_cdp_session(page);cdp.send('Page.enable')
 page.on('pageerror',lambda error:print('PAGE ERROR:',error,flush=True))
 # Register scripts in the world specified by the actual extension manifest.
 for entry in manifest['content_scripts']:
  source='\n'.join((root/'browser_extension'/f).read_text('utf-8-sig') for f in entry['js'])
  args={'source':source}
  if entry['world']=='ISOLATED':
   args['worldName']='clouddesk-extension-test'
   args['source']="globalThis.chrome={runtime:{onMessage:{addListener(fn){globalThis.receive=fn;}}}};\n"+source
  cdp.send('Page.addScriptToEvaluateOnNewDocument',args)
 page.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body=html))
 page.goto('https://dash.cloudflare.com/profile/api-tokens?clouddesk_setup=full')
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')",timeout=30000)
 assert page.evaluate('submitted')==0
 # Create a clean URL and exercise popup -> isolated bridge -> MAIN adapter.
 page.goto('https://dash.cloudflare.com/profile/api-tokens')
 frame=cdp.send('Page.getFrameTree')['frameTree']['frame']['id']
 context=cdp.send('Page.createIsolatedWorld',{'frameId':frame,'worldName':'clouddesk-extension-test'})['executionContextId']
 result=cdp.send('Runtime.evaluate',{'contextId':context,'expression':"new Promise(resolve=>receive({type:'clouddesk-fill',mode:'full'},null,resolve))",'awaitPromise':True,'returnByValue':True})
 assert result['result']['value']['ok'],result
 page.wait_for_function("document.querySelector('#clouddesk-assistant')?.textContent.includes('13 项权限已填写并校验')",timeout=30000)
 # Ensure extension APIs and state are not needed in the page's MAIN environment.
 assert page.evaluate("typeof globalThis.receive==='undefined'")
 assert page.locator('#ip').input_value()=='192.0.2.1'
 assert page.evaluate('submitted')==0
 browser.close()
print('PASS: MAIN form interaction, ISOLATED popup bridge, clean-URL retry, page event constructors; no submit/IP change')
