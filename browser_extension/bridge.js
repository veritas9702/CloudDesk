/* Only forwards a bounded permission mode. No tokens, page contents or arbitrary code. */
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message?.type!=='clouddesk-fill' || !['basic','full'].includes(message.mode)) return;
  const id=crypto.randomUUID();
  const receive=event=>{
    let result;try{result=JSON.parse(event.detail);}catch{return;}
    if(result.id!==id) return;
    clearTimeout(timer);document.removeEventListener('clouddesk:reply',receive);
    reply({ok:result.ok===true,message:String(result.message || '').slice(0,250)});
  };
  const timer=setTimeout(()=>{document.removeEventListener('clouddesk:reply',receive);reply({ok:false,message:'网页助手未响应，请刷新页面；若仍失败请确认扩展版本。'});},2500);
  document.addEventListener('clouddesk:reply',receive);
  document.dispatchEvent(new CustomEvent('clouddesk:fill',{detail:JSON.stringify({id,mode:message.mode})}));
  return true;
});
