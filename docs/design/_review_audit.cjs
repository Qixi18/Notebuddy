const { execFile } = require('child_process')
const os = require('os'), path = require('path'), fs = require('fs')
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9535
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nbaud-'))
const OUT = 'D:/notebuddy_main/Notebuddy/docs/design/_review'
const get = (u) => new Promise((res, rej) => require('http').get(u, (r) => { let d = ''; r.on('data', (c) => d += c); r.on('end', () => res(d)) }).on('error', rej))

const TARGETS = [
  { name: 'home', url: 'http://127.0.0.1:5173/', wait: 5000 },
  { name: 'courses', url: 'http://127.0.0.1:5173/courses', wait: 4500 },
  { name: 'assistant', url: 'http://127.0.0.1:5173/courses/ebd3abe1-dd62-4155-8d9c-09102c1d0e5a/assistant', wait: 6500 },
]

const AUDIT = `(function(){
  function lum(rgb){
    var c = rgb.map(function(v){ v=v/255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); });
    return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2];
  }
  function parse(s){
    var m = s && s.match(/rgba?\\(([^)]+)\\)/);
    if(!m) return null;
    var p = m[1].split(',').map(function(x){return parseFloat(x)});
    return { rgb:[p[0],p[1],p[2]], a: p.length>3? p[3] : 1 };
  }
  function bgOf(el){
    var n = el;
    while(n && n.nodeType===1){
      var c = parse(getComputedStyle(n).backgroundColor);
      if(c && c.a>0.5) return c.rgb;
      n = n.parentElement;
    }
    return [253,251,243];
  }
  var all = [].slice.call(document.querySelectorAll('*'));
  var inKatex = function(el){ var n=el; while(n && n.nodeType===1){ if((n.className||'').toString().indexOf('katex')>=0) return true; n=n.parentElement; } return false; };

  var sizes = {}, tiny=0, uiText=0, contrastFails = [], contrastChecked=0;
  all.forEach(function(el){
    var own = [].slice.call(el.childNodes).filter(function(n){return n.nodeType===3 && n.textContent.trim()}).map(function(n){return n.textContent.trim()}).join(' ');
    if(!own) return;
    if(inKatex(el)) return;              // 排除公式渲染内部节点
    var cs = getComputedStyle(el);
    if(cs.visibility==='hidden' || cs.display==='none') return;
    if(parseFloat(cs.opacity) < 0.1) return;
    var fs = parseFloat(cs.fontSize);
    uiText++;
    var key = (Math.round(fs*10)/10)+'px';
    sizes[key] = (sizes[key]||0)+1;
    if(fs < 12) tiny++;
    var fg = parse(cs.color); if(!fg || fg.a<0.5) return;
    var bg = bgOf(el);
    var L1 = lum(fg.rgb), L2 = lum(bg);
    var ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    var bold = parseInt(cs.fontWeight,10) >= 700;
    var isLarge = fs >= 24 || (bold && fs >= 18.66);
    var need = isLarge ? 3 : 4.5;
    contrastChecked++;
    if(ratio < need){
      contrastFails.push({ txt: own.slice(0,28), fs: key, fg: cs.color, bg: 'rgb('+bg.join(',')+')',
        ratio: Math.round(ratio*100)/100, need: need, cls: (el.className||'').toString().slice(0,40) });
    }
  });

  var targets = [].slice.call(document.querySelectorAll('button,a[href],input,select,textarea,[role=button]'));
  var t24=0, t44=0, tTotal=0, samples=[];
  targets.forEach(function(el){
    var r = el.getBoundingClientRect();
    if(r.width<=0 || r.height<=0) return;
    tTotal++;
    if(r.height<24 || r.width<24) t24++;
    if(r.height<44 || r.width<44){ t44++; if(samples.length<8) samples.push({h:Math.round(r.height), w:Math.round(r.width), txt:(el.textContent||'').trim().slice(0,16)||el.getAttribute('aria-label')||'(icon)'}); }
  });

  return JSON.stringify({
    uiTextNodes: uiText,
    tinyTextUnder12: tiny,
    topSizes: Object.keys(sizes).sort(function(a,b){return sizes[b]-sizes[a]}).slice(0,10).map(function(k){return k+' x'+sizes[k]}),
    contrastChecked: contrastChecked,
    contrastFails: contrastFails.length,
    contrastFailSamples: contrastFails.slice(0,10),
    targets: { total: tTotal, under24: t24, under44: t44, samples: samples }
  },null,1)
})()`

;(async () => {
  const child = execFile(CHROME, ['--headless=new', `--remote-debugging-port=${PORT}`, '--remote-allow-origins=*',
    `--user-data-dir=${profile}`, '--window-size=1440,900', '--no-first-run', 'about:blank'], () => {})
  let list = null
  for (let i = 0; i < 80; i++) { try { list = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)); break } catch { await new Promise(r => setTimeout(r, 250)) } }
  const page = list.find(t => t.type === 'page' && t.webSocketDebuggerUrl)
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  let id = 0; const p = new Map()
  await new Promise(r => ws.addEventListener('open', r))
  ws.addEventListener('message', (e) => { const m = JSON.parse(e.data); if (m.id && p.has(m.id)) { p.get(m.id)(m); p.delete(m.id) } })
  const send = (m, params = {}) => new Promise(res => { const i = ++id; p.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params })) })
  const ev = async (x) => (await send('Runtime.evaluate', { expression: x, returnByValue: true, awaitPromise: true })).result?.result?.value
  const wait = (ms) => new Promise(r => setTimeout(r, ms))
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false })

  const out = {}
  for (const t of TARGETS) {
    await send('Page.navigate', { url: t.url })
    await wait(t.wait)
    out[t.name] = await ev(AUDIT)
  }
  fs.writeFileSync(path.join(OUT, 'audit.json'), JSON.stringify(out, null, 1))
  console.log('done')
  ws.close(); child.kill(); try { fs.rmSync(profile, { recursive: true, force: true }) } catch {}
  process.exit(0)
})()
