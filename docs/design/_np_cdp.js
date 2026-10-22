const { execFile } = require('child_process');
const os=require('os'), path=require('path'), fs=require('fs');
const CHROME='C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT=9521, profile=fs.mkdtempSync(path.join(os.tmpdir(),'np-'));
const get=u=>new Promise((res,rej)=>require('http').get(u,r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(d))}).on('error',rej));
(async()=>{
  const child=execFile(CHROME,['--headless=new',`--remote-debugging-port=${PORT}`,'--remote-allow-origins=*',`--user-data-dir=${profile}`,'--window-size=1600,1000','--no-first-run','http://127.0.0.1:5173/courses/ebd3abe1-dd62-4155-8d9c-09102c1d0e5a/assistant'],()=>{});
  let list=null; for(let i=0;i<60;i++){try{list=JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`));break}catch{await new Promise(r=>setTimeout(r,250))}}
  const page=list.find(t=>t.type==='page'&&t.webSocketDebuggerUrl);
  const ws=new WebSocket(page.webSocketDebuggerUrl); let id=0; const p=new Map();
  await new Promise(r=>ws.addEventListener('open',r));
  ws.addEventListener('message',e=>{const m=JSON.parse(e.data); if(m.id&&p.has(m.id)){p.get(m.id)(m);p.delete(m.id)}});
  const send=(m,params={})=>new Promise(res=>{const i=++id;p.set(i,res);ws.send(JSON.stringify({id:i,method:m,params}))});
  const ev=async x=>(await send('Runtime.evaluate',{expression:x,returnByValue:true})).result?.result?.value;
  const wait=ms=>new Promise(r=>setTimeout(r,ms));
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await wait(6000);

  const step = async (label, expr) => console.log(label, await ev(expr));

  // 1. 新建会话
  await ev(`(function(){var b=[].slice.call(document.querySelectorAll('button')).filter(function(x){return x.textContent.indexOf('新对话')>=0})[0];
    if(b){b.click();return b.textContent.trim()} return 'no button'})()`);
  await wait(1200);
  // 2. 打开范围菜单
  await ev(`(function(){var t=document.querySelector('.workspace-scope-trigger'); if(t){t.click();return 'opened'} return 'no trigger'})()`);
  await wait(500);
  // 3. 点「锁定笔记」
  console.log('pick locked-note:', await ev(`(function(){
    var b=[].slice.call(document.querySelectorAll('[role=menuitemradio]')).filter(function(x){return x.textContent.trim()==='锁定笔记'})[0];
    if(b){b.click();return 'clicked'} return 'not found'})()`));
  await wait(900);

  await step('dialog:', `(function(){
    var d=document.querySelector('[role=dialog][aria-label="选择要锁定的笔记"]');
    if(!d) return 'NO DIALOG';
    return JSON.stringify({
      hasSelect: !!d.querySelector('select[aria-label="按课程筛选笔记"]'),
      hasSearch: !!d.querySelector('input[aria-label="搜索笔记名称"]'),
      courseOptions: [].slice.call(d.querySelectorAll('select option')).map(function(o){return o.textContent}),
      items: d.querySelectorAll('.note-picker-item').length,
      count: (d.querySelector('.note-picker-count')||{}).textContent,
      titles: [].slice.call(d.querySelectorAll('.note-picker-title')).slice(0,3).map(function(e){return e.textContent}),
    }, null, 1)})()`);

  // 4. 搜索过滤
  console.log('search:', await ev(`(function(){
    var inp=document.querySelector('input[aria-label="搜索笔记名称"]');
    var before=document.querySelectorAll('.note-picker-item').length;
    var setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    setter.call(inp,'设计');
    inp.dispatchEvent(new Event('input',{bubbles:true}));
    return 'typed, before='+before})()`));
  await wait(500);
  await step('after search:', `(function(){
    var d=document.querySelector('[role=dialog][aria-label="选择要锁定的笔记"]');
    return JSON.stringify({items: d.querySelectorAll('.note-picker-item').length,
      titles: [].slice.call(d.querySelectorAll('.note-picker-title')).map(function(e){return e.textContent}).slice(0,5),
      count:(d.querySelector('.note-picker-count')||{}).textContent})})()`);

  // 5. 选一门别的课程
  console.log('switch course:', await ev(`(function(){
    var sel=document.querySelector('select[aria-label="按课程筛选笔记"]');
    var opts=[].slice.call(sel.options); var target=opts.find(function(o){return o.value && o.value!==sel.value});
    if(!target) return 'only one course';
    var setter=Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype,'value').set;
    setter.call(sel,target.value); sel.dispatchEvent(new Event('change',{bubbles:true}));
    return target.textContent})()`));
  await wait(1800);
  await step('after switch:', `(function(){
    var d=document.querySelector('[role=dialog][aria-label="选择要锁定的笔记"]');
    return JSON.stringify({items: d.querySelectorAll('.note-picker-item').length,
      withCourse: d.querySelectorAll('.note-picker-course').length,
      count:(d.querySelector('.note-picker-count')||{}).textContent})})()`);

  // 6. 选一篇笔记
  console.log('pick note:', await ev(`(function(){
    var b=document.querySelector('.note-picker-item');
    if(!b) return 'no item';
    var t=b.querySelector('.note-picker-title').textContent; b.click(); return t})()`));
  await wait(800);
  await step('scope after pick:', `(function(){
    var trig=document.querySelector('.workspace-scope-trigger');
    return JSON.stringify({dialogOpen: !!document.querySelector('[role=dialog][aria-label="选择要锁定的笔记"]'),
      scopeLabel: trig? trig.textContent.trim() : null})})()`);

  const shot=await send('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync('D:/notebuddy_main/Notebuddy/docs/design/mock-dividers/note-picker.png', Buffer.from(shot.result.data,'base64'));
  ws.close(); child.kill(); try{fs.rmSync(profile,{recursive:true,force:true})}catch{}
})();
