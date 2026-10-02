/* Capture setup intent before the dashboard removes its URL parameters. */
(() => {
  if(globalThis.cloudDeskAssistantStarted) return;
  globalThis.cloudDeskAssistantStarted=true;
  const key='clouddesk.pending-permissions.v1';
  const valid=mode=>['basic','full'].includes(mode);
  function intent() {
    const initial=new URL(location.href);
    let mode=initial.searchParams.get('clouddesk_setup');
    if(!valid(mode)) {
      try {const next=new URL(initial.searchParams.get('redirect_uri') || '',location.origin);
        if(next.origin===location.origin) mode=next.searchParams.get('clouddesk_setup');} catch {}
    }
    try {
      if(valid(mode)) sessionStorage.setItem(key,JSON.stringify({mode,expires:Date.now()+900000}));
      else {const pending=JSON.parse(sessionStorage.getItem(key) || 'null');
        if(pending?.expires>Date.now() && valid(pending.mode)) mode=pending.mode;
        else sessionStorage.removeItem(key);}
    } catch {}
    return valid(mode)?mode:null;
  }
  const initialMode=intent();
  let running=false,stopRun=null;
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  const tokenPage=()=>location.origin==='https://dash.cloudflare.com' && /^\/profile\/api-tokens(?:\/|$)/.test(location.pathname);
  function panel() {
    document.getElementById('clouddesk-assistant')?.remove();
    const box=document.createElement('aside');
    box.id='clouddesk-assistant';box.setAttribute('aria-live','polite');
    box.style.cssText='position:fixed;top:12px;right:12px;z-index:2147483647;max-width:340px;padding:16px;background:#fff;color:#20324b;border:2px solid #f08b28;border-radius:10px;box-shadow:0 4px 20px #0002;font:14px/1.6 system-ui,sans-serif';
    const title=document.createElement('strong');title.textContent='CloudDesk 权限助手 0.1.5';
    const message=document.createElement('p');message.textContent='助手已启动，等待令牌权限表单…';
    const stop=document.createElement('button');stop.textContent='停止';
    box.append(title,message,stop);document.body.append(box);
    return {box,message,stop};
  }
  async function run(mode) {
    if(running || !valid(mode)) return;
    running=true;
    let stopped=false;stopRun=()=>{stopped=true;};
    try {
      // Let normal login complete; never interact with verification controls.
      const loginDeadline=Date.now()+900000;
      while(!document.body || !tokenPage()) {
        if(stopped || Date.now()>loginDeadline) return;
        await delay(250);
      }
      const {box,message,stop}=panel();stop.onclick=()=>{stopped=true;stop.disabled=true;};
      try {
        const deadline=Date.now()+15000;
        while(!CloudDeskForm.rows().length) {
          if(stopped) throw Error('已停止。未完成权限填写，请勿直接创建。');
          if(!tokenPage()) throw Error('已离开令牌页面，停止填写。');
          if(Date.now()>deadline) throw Error('未识别到权限表单。请打开创建令牌页面，再点右上角 CD 助手重试；若已经在表单页，说明当前控件未匹配，请勿创建。');
          await delay(100);
        }
        try {sessionStorage.removeItem(key);} catch {}
        const plan=CloudDeskCatalog[mode];
        // Reapply existing rows on retry; append only missing rows, then verify all fields.
        let count;
        count=await CloudDeskForm.fill(plan,text=>{message.textContent=text;},()=>stopped);
        box.style.borderColor='#248654';
        message.textContent=`${count} 项权限已填写并校验。请核对资源范围，填写 IP 白名单，然后由你确认创建。`;
      } catch(error) {
        box.style.borderColor='#c34836';message.textContent=error.message;
        const diagnostic=document.createElement('button');diagnostic.textContent='复制权限控件诊断';
        diagnostic.onclick=async()=>{
          const value=JSON.stringify(CloudDeskForm.diagnostics(),null,2);
          try {await navigator.clipboard.writeText(value);diagnostic.textContent='已复制，请粘贴给开发者';}
          catch {const area=document.createElement('textarea');area.readOnly=true;area.value=value;area.style.cssText='width:100%;height:120px';box.append(area);area.select();diagnostic.textContent='请复制下方诊断内容';}
        };
        box.append(diagnostic);
      } finally {
        try {sessionStorage.removeItem(key);} catch {}
        stop.textContent='关闭提示';stop.disabled=false;stop.onclick=()=>box.remove();
      }
    } finally {running=false;stopRun=null;}
  }
  // Works on clean dashboard URLs too: no query parameter is required for retry.
  function requestFill(message,reply) {
    if(!['basic','full'].includes(message?.mode)) return;
    if(!tokenPage()) {reply({ok:false,message:'请先进入 Cloudflare 用户令牌创建页面。'});return;}
    if(running) {reply({ok:false,message:'助手正在处理，请查看网页右上角提示。'});return;}
    run(message.mode);reply({ok:true,message:'已启动，请查看网页右上角的填写结果。'});
  }
  document.addEventListener('clouddesk:fill',event=>{
    let message;try{message=JSON.parse(event.detail);}catch{return;}
    if(typeof message?.id!=='string' || message.id.length>80)return;
    requestFill(message,result=>document.dispatchEvent(new CustomEvent('clouddesk:reply',{detail:JSON.stringify({id:message.id,...result})})));
  });
  if(initialMode) run(initialMode);
})();
