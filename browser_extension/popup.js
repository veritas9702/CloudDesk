for(const mode of ['full','basic']) document.getElementById(mode).addEventListener('click',async()=>{
 const status=document.getElementById('status');
 try {
  const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
  if(!tab?.id) throw Error('没有可用的网页标签。');
  const result=await chrome.tabs.sendMessage(tab.id,{type:'clouddesk-fill',mode});
  status.textContent=result?.message || '未收到助手响应，请刷新令牌页面后重试。';
 } catch {
  status.textContent='未连接到网页。请刷新 Cloudflare 令牌页后重试；更新助手后需在扩展管理页点重新加载。';
 }
});
