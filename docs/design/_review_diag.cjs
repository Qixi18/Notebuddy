const { execFile } = require('child_process')
const os = require('os'), path = require('path'), fs = require('fs')
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9534
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nbdiag-'))
const get = (u) => new Promise((res, rej) => require('http').get(u, (r) => { let d = ''; r.on('data', (c) => d += c); r.on('end', () => res(d)) }).on('error', rej))

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
  await send('Page.navigate', { url: 'http://127.0.0.1:5173/courses/ebd3abe1-dd62-4155-8d9c-09102c1d0e5a/assistant' })
  await wait(6500)

  console.log(await ev(`(function(){
    var out={};
    // 1. 18.15px 元素溯源
    var big=[].slice.call(document.querySelectorAll('*')).filter(function(el){
      return Math.abs(parseFloat(getComputedStyle(el).fontSize)-18.15)<0.05 && el.textContent.trim();
    });
    out.sample1815 = big.slice(0,5).map(function(el){
      return {tag:el.tagName, cls:(el.className||'').toString().slice(0,60), txt:el.textContent.trim().slice(0,40),
              fs:getComputedStyle(el).fontSize, parentCls:(el.parentElement&&el.parentElement.className||'').toString().slice(0,60)};
    });
    out.count1815 = big.length;
    // 2. 1px 元素溯源
    var one=[].slice.call(document.querySelectorAll('*')).filter(function(el){return Math.abs(parseFloat(getComputedStyle(el).fontSize)-1)<0.01});
    out.sample1px = one.slice(0,5).map(function(el){return {tag:el.tagName, cls:(el.className||'').toString().slice(0,70)}});
    out.count1px = one.length;
    // 3. 触摸目标过小的可交互元素
    var small=[].slice.call(document.querySelectorAll('button,a[href],input,select,textarea')).filter(function(el){
      var r=el.getBoundingClientRect();
      return r.width>0 && r.height>0 && (r.height<32 || r.width<32);
    });
    out.smallTargets = small.length;
    out.smallTargetSamples = small.slice(0,10).map(function(el){
      var r=el.getBoundingClientRect();
      return {tag:el.tagName, cls:(el.className||'').toString().slice(0,45), w:Math.round(r.width), h:Math.round(r.height), txt:(el.textContent||'').trim().slice(0,18), aria:el.getAttribute('aria-label')};
    });
    // 4. 无 aria-label 且无文本内容的按钮（图标按钮）
    var iconBtns=[].slice.call(document.querySelectorAll('button')).filter(function(el){
      return !el.textContent.trim() && !el.getAttribute('aria-label') && !el.getAttribute('title');
    });
    out.unlabeledIconButtons = iconBtns.length;
    out.unlabeledSamples = iconBtns.slice(0,6).map(function(el){return (el.className||'').toString().slice(0,50)});
    // 5. 横向溢出
    out.docScrollW = document.documentElement.scrollWidth;
    out.docClientW = document.documentElement.clientWidth;
    // 6. 标题层级
    out.headings = [].slice.call(document.querySelectorAll('h1,h2,h3,h4,h5,h6')).map(function(h){return h.tagName});
    return JSON.stringify(out,null,1)
  })()`))

  ws.close(); child.kill(); try { fs.rmSync(profile, { recursive: true, force: true }) } catch {}
  process.exit(0)
})()
