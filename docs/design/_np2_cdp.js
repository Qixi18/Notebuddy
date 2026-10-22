const { execFile } = require('child_process');
const os=require('os'), path=require('path'), fs=require('fs');
const CHROME='C://Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT=9525, profile=fs.mkdtempSync(path.join(os.tmpdir(),'np2-'));
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
  await ev(`(function(){var b=[].slice.call(document.querySelectorAll('button')).filter(function(x){return x.textContent.indexOf('新对话')>=0})[0]; if(b)b.click(); return 1})()`);
  await wait(1200);
  await ev(`document.querySelector('.workspace-scope-trigger').click()`); await wait(400);
  await ev(`(function(){var b=[].slice.call(document.querySelectorAll('[role=menuitemradio]')).filter(function(x){return x.textContent.trim()==='锁定笔记'})[0]; if(b)b.click(); return 1})()`);
  await wait(1200);
  console.log('dialog open:', await ev(`!!document.querySelector('[role=dialog][aria-label="选择要锁定的笔记"]')`));
  const shot=await send('Page.captureScreenshot',{format:'png'});
  fs.writeFileSync('D:/notebuddy_main/Notebuddy/docs/design/mock-dividers/note-picker-open.png', Buffer.from(shot.result.data,'base64'));
  ws.close(); child.kill(); try{fs.rmSync(profile,{recursive:true,force:true})}catch{}
})();
