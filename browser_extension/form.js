/* Visible form adapter. No fetch, cookies, credential extraction or submit. */
globalThis.CloudDeskForm = (() => {
  let stage='尚未开始', lastFailure=null,searchAttempts=[];
  const confirmed=new Map();
  const controlsSelector = 'select,[role="combobox"]';
  const visible = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
  const normalize = s => String(s || '').trim().replace(/\s+/g, ' ').toLowerCase();
  const matches = (text, names) => names.some(n => normalize(n) === normalize(text));
  const controls = e => Array.from(e.querySelectorAll(controlsSelector)).filter(visible)
    .filter(x => !x.parentElement.closest('[role="combobox"]'));
  function texts(c) {
    if(c.tagName === 'SELECT') return [c.selectedOptions[0]?.textContent || ''];
    const result=[];
    for(let e=c,i=0;e && i<6;e=e.parentElement,i++) {
      if(controls(e).length>1) break;
      // A search query is not a committed permission selection.
      result.push(e===c && c.tagName==='INPUT' ? '' : (e.value || ''), e.textContent || '');
    }
    return result;
  }
  function rows() {
    const found=[];
    for(const c of controls(document)) {
      for(let e=c.parentElement;e && e!==document.body;e=e.parentElement) {
        const cs=controls(e);
        if(cs.length>3) break;
        if(cs.length===3) {
          const scopeNames=['Zone','Account','区域','账户','帐户'];
          const first=cs[0];
          const scope=texts(first).some(t=>matches(t,scopeNames)) ||
            (first.tagName==='SELECT' && Array.from(first.options).some(o=>matches(o.textContent,scopeNames))) ||
            (first.tagName==='BUTTON' && cs[1].tagName==='INPUT' && cs[2].tagName==='BUTTON');
          if(scope && !found.includes(e)) found.push(e);
          break;
        }
      }
    }
    return found;
  }
  function fieldKey(c) {
    for(const [i,row] of rows().entries()) {const j=controls(row).indexOf(c);if(j>=0)return `${i}:${j}`;}
    return null;
  }
  document.addEventListener('input',event=>{const key=fieldKey(event.target);if(key!==null)confirmed.delete(key);},true);
  function selected(c,key) {
    if(c.tagName!=='INPUT') return texts(c);
    // Input-only display is valid only after an observed option selection.
    return confirmed.has(key) ? [...texts(c),c.value || ''] : [];
  }
  const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function guard(cancelled) {
    if(cancelled()) throw Error('已停止填写。当前权限可能不完整，请勿直接创建。');
    if(location.origin!=='https://dash.cloudflare.com' || !location.pathname.startsWith('/profile/api-tokens'))
      throw Error('当前不是 Cloudflare 用户令牌页面，未继续填写。');
  }
  async function wait(find,cancelled,timeout=6000) {
    const deadline=Date.now()+timeout;
    while(Date.now()<deadline) {
      guard(cancelled);
      const value=find(); if(value) return value;
      await delay(100);
    }
    throw Error('网页未出现预期控件。已停止，请勿直接按不完整权限创建。');
  }
  function unique(elements,names) {
    // Prefer documented English name, then presentation aliases.
    for(const name of names) {
      const found=elements.filter(e=>matches(e.textContent,[name]));
      if(found.length>1) throw Error('存在重复权限选项：'+name);
      if(found.length===1) return found[0];
    }
    return null;
  }
  function openMenu(c) {
    c.focus();c.click();
    if(c.getAttribute('aria-expanded')==='false' && c.tagName==='BUTTON') {
      c.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerType:'mouse',button:0}));
      c.dispatchEvent(new MouseEvent('mousedown',{bubbles:true,button:0}));
      c.dispatchEvent(new MouseEvent('mouseup',{bubbles:true,button:0}));
      c.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerType:'mouse',button:0}));
    }
  }
  function menuOptions(c) {
    const id=c.getAttribute('aria-controls') || c.getAttribute('aria-owns');
    const menu=id && document.getElementById(id);
    return Array.from((menu || document).querySelectorAll('[role="option"]'))
      .filter(visible).filter(o=>o.getAttribute('aria-disabled')!=='true' && !o.disabled);
  }
  async function select(resolve,names,cancelled,key) {
    const c=resolve();
    guard(cancelled);
    if(c.tagName!=='INPUT' && texts(c).some(t=>matches(t,names))) return;
    c.scrollIntoView({block:'nearest'});
    if(c.tagName==='SELECT') {
      const option=await wait(()=>{const current=resolve();return current?.tagName==='SELECT' && unique(Array.from(current.options).filter(o=>!o.disabled),names);},cancelled);
      const current=resolve();
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(current,option.value);
      current.dispatchEvent(new Event('change',{bubbles:true}));
    } else if(c.tagName==='INPUT') {
      // Cloudflare uses a searchable input for the permission name, not a button.
      let option=null;searchAttempts=[];
      for(const query of names) {
        guard(cancelled);
        const current=resolve();current.focus();
        const trace={query,before:current.value};searchAttempts.push(trace);
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(current,query);
        current.dispatchEvent(new InputEvent('input',{bubbles:true,composed:true,inputType:'insertText',data:query}));
        current.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',code:'ArrowDown',bubbles:true,composed:true}));
        current.dispatchEvent(new KeyboardEvent('keyup',{key:'ArrowDown',code:'ArrowDown',bubbles:true,composed:true}));
        trace.afterInput=resolve()?.value;
        const deadline=Date.now()+1800;
        while(Date.now()<deadline) {
          guard(cancelled);
          const live=resolve();option=live && unique(menuOptions(live),names);
          if(option) break;
          await delay(100);
        }
        trace.afterWait=resolve()?.value;trace.expanded=resolve()?.getAttribute('aria-expanded');trace.optionFound=!!option;
        if(option) break;
      }
      if(!option) throw Error('已输入权限搜索词，但没有找到匹配选项；请复制权限控件诊断。');
      option.click();
      await wait(()=>{const live=resolve();return live && live.getAttribute('aria-expanded')!=='true' && !visible(option);},cancelled);
      const current=resolve();current.blur();
      await wait(()=>{const live=resolve();return live && [...texts(live),live.value || ''].some(t=>matches(t,names));},cancelled);
      confirmed.set(key,true);
    } else {
      openMenu(c);
      const option=await wait(()=>{const current=resolve();return current && unique(menuOptions(current),names);},cancelled);
      option.click();
    }
    await wait(()=>{const current=resolve();return current && current.getAttribute('aria-expanded')!=='true' && selected(current,key).some(t=>matches(t,names));},cancelled);
  }
  async function addRow(index,cancelled) {
    const previous=rows()[index-1];
    const labels=['Add more','添加更多','新增更多','+ Add more','+ 添加更多'];
    for(let e=previous.parentElement;e && e!==document.body;e=e.parentElement) {
      const buttons=Array.from(e.querySelectorAll('button,[role="button"],a')).filter(visible).filter(b=>matches(b.textContent,labels));
      if(buttons.length===1) {buttons[0].click();await wait(()=>rows().length===index+1,cancelled);return;}
      if(buttons.length>1) break;
    }
    throw Error('未找到权限区域唯一的“添加更多”按钮，已停止。');
  }
  function verify(plan,cancelled=()=>false) {
    guard(cancelled);
    const rs=rows();
    if(rs.length!==plan.length) throw Error('权限数量与计划不一致，未完成填写。');
    plan.forEach((row,i)=>[row.scope,row.names,row.access].forEach((names,col)=>{
      if(!selected(controls(rs[i])[col],`${i}:${col}`).some(t=>matches(t,names))) throw Error('权限校验失败：'+row.title);
    }));
    return plan.length;
  }
  async function fill(plan,progress=()=>{},cancelled=()=>false) {
    lastFailure=null;stage='检查初始权限';
    guard(cancelled);
    const existing=rows().length;
    if(!existing || existing>plan.length) throw Error('当前权限行数超出本次配置范围。请从工具打开新的创建页；不会删除额外权限。');
    confirmed.clear();
    for(let i=0;i<plan.length;i++) {
      guard(cancelled); if(i>=rows().length) await addRow(i,cancelled);
      progress(`正在填写 ${i+1}/${plan.length}：${plan[i].title}`);
      for(const [col,names] of [plan[i].scope,plan[i].names,plan[i].access].entries()) {
        stage=`第 ${i+1} 行 / ${['范围','权限名称','操作级别'][col]} / ${names[0]}`;
        try {await select(()=>{const row=rows()[i];return row && controls(row)[col];},names,cancelled,`${i}:${col}`);}
        catch(error) {lastFailure=diagnostics();throw Error(stage+'：'+error.message);}
      }
    }
    return verify(plan,cancelled);
  }
  function diagnostics() {
    // Deliberately exclude page HTML, URLs, non-permission inputs, account/resource selectors and tokens.
    return {helper:'0.1.5',stage,searchAttempts,rows:rows().map(row=>controls(row).map(c=>({
      tag:c.tagName,role:c.getAttribute('role'),expanded:c.getAttribute('aria-expanded'),
      permissionInputText:c.tagName==='INPUT'?(c.value || '').slice(0,100):null,disabled:!!c.disabled,readOnly:!!c.readOnly,autocomplete:c.getAttribute('aria-autocomplete'),selected:texts(c).filter(Boolean).map(t=>t.trim().slice(0,100)).slice(0,3),
      options:c.tagName==='SELECT'?Array.from(c.options).slice(0,150).map(o=>({label:o.textContent.trim().slice(0,100),disabled:o.disabled})):(c.getAttribute('aria-expanded')==='true'?menuOptions(c).slice(0,150).map(o=>({label:o.textContent.trim().slice(0,100)})):[])
    }))),visibleOptionCount:Array.from(document.querySelectorAll('[role="option"]')).filter(visible).length};
  }
  return {fill,verify,rows,diagnostics:()=>lastFailure || diagnostics()};
})();
