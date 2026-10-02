import json
from tools.generate_extension import catalog
names=sorted({r['names'][0] for r in catalog()['full']})
html='''<html><meta charset="utf-8"><body><section><div id="rows"></div><button onclick="add()">添加更多</button></section><input id="ip" value="192.0.2.1"><button onclick="submitted++">创建令牌</button>
<script>window.submitted=0;window.searches=0;window.chosen=0;
const NAMES=__NAMES__;let seq=0;
function menu(control,options,commit){document.querySelectorAll('[role=listbox]').forEach(x=>x.remove());const list=document.createElement('div');list.id='menu'+(++seq);list.setAttribute('role','listbox');control.setAttribute('aria-controls',list.id);control.setAttribute('aria-expanded','true');
 for(const name of options){const option=document.createElement('div');option.setAttribute('role','option');option.textContent=name;option.onclick=()=>{chosen++;commit(name);control.setAttribute('aria-expanded','false');list.remove();};list.append(option);}document.body.append(list);}
function button(names,value){const b=document.createElement('button');b.setAttribute('role','combobox');b.setAttribute('aria-expanded','false');b.textContent=value;b.onpointerdown=()=>menu(b,names,n=>b.textContent=n);return b;}
function add(){const row=document.createElement('div');row.className='row';const scope=button(['区域','账户'],'区域');const wrap=document.createElement('div');const selected=document.createElement('span');selected.textContent='区域';const input=document.createElement('input');input.setAttribute('role','combobox');input.setAttribute('aria-expanded','false');input.oninput=()=>{searches++;const query=input.value;setTimeout(()=>menu(input,NAMES.filter(n=>n.toLowerCase().includes(query.toLowerCase())),n=>{selected.textContent=n;input.value='';}),30);};wrap.append(selected,input);const access=button(['读取','编辑','清除'],'读取');row.append(scope,wrap,access);document.querySelector('#rows').append(row);}add();
</script></body></html>'''.replace('__NAMES__',json.dumps(names))
