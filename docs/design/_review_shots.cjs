const { execFile } = require('child_process')
const os = require('os'), path = require('path'), fs = require('fs')
const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'
const PORT = 9533
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nbrev-'))
const OUT = 'D:/notebuddy_main/Notebuddy/docs/design/_review'
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true })

const get = (u) => new Promise((res, rej) => require('http').get(u, (r) => { let d = ''; r.on('data', (c) => d += c); r.on('end', () => res(d)) }).on('error', rej))

const TARGETS = [
  { name: '01-home', url: 'http://127.0.0.1:5173/', wait: 5000 },
  { name: '02-courses', url: 'http://127.0.0.1:5173/courses', wait: 4500 },
  { name: '03-assistant', url: 'http://127.0.0.1:5173/courses/ebd3abe1-dd62-4155-8d9c-09102c1d0e5a/assistant', wait: 6000 },
]

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
  await send('Page.enable')

  const report = {}

  for (const t of TARGETS) {
    await send('Page.navigate', { url: t.url })
    await wait(t.wait)
    const shot = await send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(path.join(OUT, t.name + '.png'), Buffer.from(shot.result.data, 'base64'))

    // 采集实际计算样式：验证 token 落地情况
    const stats = await ev(`(function(){
      var all = [].slice.call(document.querySelectorAll('*'));
      var seen = {}; var tiny = 0; var total = 0;
      var colors = {};
      all.forEach(function(el){
        if(!el.textContent || !el.textContent.trim()) return;
        if(el.children.length && el.children.length>0){
          var own=[].slice.call(el.childNodes).filter(function(n){return n.nodeType===3 && n.textContent.trim()}).length;
          if(!own) return;
        }
        var cs = getComputedStyle(el);
        var fs = parseFloat(cs.fontSize);
        total++;
        if(fs>0){ seen[cs.fontSize]=(seen[cs.fontSize]||0)+1; if(fs<12) tiny++; }
        if(cs.color) colors[cs.color]=(colors[cs.color]||0)+1;
      });
      var root=getComputedStyle(document.documentElement);
      return JSON.stringify({
        title: document.title,
        textNodes: total,
        tinyText: tiny,
        fontSizeHistogram: Object.keys(seen).sort(function(a,b){return seen[b]-seen[a]}).slice(0,12).map(function(k){return k+' x'+seen[k]}),
        topTextColors: Object.keys(colors).sort(function(a,b){return colors[b]-colors[a]}).slice(0,8),
        tokens: {
          nbWhite: root.getPropertyValue('--nb-white').trim(),
          nbForest: root.getPropertyValue('--nb-forest').trim(),
          blue: root.getPropertyValue('--blue').trim(),
          nbSans: root.getPropertyValue('--nb-sans').trim(),
          ink: root.getPropertyValue('--ink').trim()
        }
      },null,1)
    })()`)
    report[t.name] = stats
    console.log('=== ' + t.name + ' ===')
    console.log(stats)
  }

  fs.writeFileSync(path.join(OUT, 'computed-styles.json'), JSON.stringify(report, null, 1))
  ws.close(); child.kill(); try { fs.rmSync(profile, { recursive: true, force: true }) } catch {}
  process.exit(0)
})()
