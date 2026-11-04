/* 首屏：各市场收盘结论色块墙。后端 /api/overview；没有后端时读 static/demo/overview.json（GitHub Pages）。 */
(() => {
const $ = s => document.querySelector(s);
const fmt = x => x == null ? '-' : Number(x).toLocaleString('en-US', {minimumFractionDigits: Math.abs(x) < 10 ? 3 : 2, maximumFractionDigits: Math.abs(x) < 10 ? 4 : 2});
const sgn = x => (x > 0 ? '+' : '') ;
let DATA = null, FILTER = 'all';

async function load() {
  try {
    const r = await fetch('/api/overview');
    if (r.ok && (r.headers.get('content-type') || '').includes('json')) return r.json();
  } catch (e) {}
  const r = await fetch('static/demo/overview.json?t=' + Date.now(), {cache: 'no-store'});  // 绕过 Pages 的 10 分钟缓存
  return r.json();
}
function spark(arr, up) {
  if (!arr || arr.length < 2) return '';
  const v = arr.filter(x => x != null), lo = Math.min(...v), hi = Math.max(...v), n = v.length;
  const pts = v.map((x, i) => `${(i / (n - 1) * 100).toFixed(1)},${(20 - (hi > lo ? (x - lo) / (hi - lo) : .5) * 18 - 1).toFixed(1)}`).join(' ');
  return `<svg viewBox="0 0 100 20" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${up ? '#f04848' : '#1fbf75'}" stroke-width="1.4" vector-effect="non-scaling-stroke"/></svg>`;
}
function tile(it) {
  const href = `chart.html?symbol=${encodeURIComponent(it.symbol)}&name=${encodeURIComponent(it.name)}&preset=${DATA.preset || 'relaxed'}`;
  if (it.error) return `<div class="tile f err" data-v="err" title="${it.error}"><div class="nm">${it.name}</div><div class="px">--</div><div class="ch">数据暂缺</div></div>`;
  const cls = it.chg_pct > 0 ? 'u' : it.chg_pct < 0 ? 'd' : 'f', col = it.chg_pct > 0 ? 'up' : it.chg_pct < 0 ? 'dn' : '';
  return `<a class="tile ${cls} ${it.tone}" data-v="${it.verdict}" href="${href}">
    ${it.live ? '<span class="lv" title="盘中实时价，结论仍按最近收盘">实时</span>' : ''}
    ${it.no_volume ? '<span class="nv" title="没有成交量，地量/天量一证无法判断">无量</span>' : ''}
    <div class="nm">${it.name}</div>
    <div class="px ${col}">${fmt(it.close)}</div>
    <div class="ch ${col}">${sgn(it.chg)}${fmt(it.chg)} ${sgn(it.chg_pct)}${it.chg_pct.toFixed(2)}%</div>
    ${spark(it.spark, it.spark.at(-1) >= it.spark[0])}
    <div class="vd"><span class="badge ${it.tone}">${it.verdict}</span><span class="ev">底${it.bottom} 顶${it.top}</span></div>
    <div class="why">${it.reason}</div>
  </a>`;
}
function render() {
  const d = DATA;
  $('#model').textContent = d.model || '';
  $('#asof').innerHTML = Object.entries(d.asof || {}).map(([k, v]) => `<span>${k} ${v}</span>`).join('') + `<span>生成 ${d.generated}</span>`;
  Object.entries(d.counts || {}).forEach(([k, v]) => { const el = $('#c' + k); if (el) el.textContent = v; });
  const t = (d.ticker || []).map(x => `<span>${x.name}<b class="${x.chg_pct >= 0 ? 'up' : 'dn'}">${fmt(x.close)}</b><span class="${x.chg_pct >= 0 ? 'up' : 'dn'}">${sgn(x.chg_pct)}${x.chg_pct.toFixed(2)}%</span> · ${x.verdict}</span>`).join('');
  $('#track').innerHTML = t + t;
  $('#groups').innerHTML = d.groups.map(g => {
    const items = g.items.filter(it => FILTER === 'all' || it.verdict === FILTER);
    if (!items.length) return '';
    return `<h2>${g.name}</h2><div class="grid">${items.map(tile).join('')}</div>`;
  }).join('') || '<div class="loading">今天没有符合条件的标的。</div>';
}
document.querySelectorAll('#filters button').forEach(b => b.onclick = () => {
  document.querySelectorAll('#filters button').forEach(x => x.classList.remove('on')); b.classList.add('on'); FILTER = b.dataset.f; render();
});
load().then(d => { DATA = d; render(); }).catch(e => { $('#groups').innerHTML = `<div class="loading">加载失败：${e.message}</div>`; });
// 自动刷新：每 3 分钟、以及切回页面时检查一次，有新数据就重绘（不用手动刷新）
async function refresh() {
  try { const d = await load(); if (!DATA || d.generated !== DATA.generated) { DATA = d; render(); } } catch (e) {}
}
setInterval(() => { if (!document.hidden) refresh(); }, 180000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
window.addEventListener('pageshow', e => { if (e.persisted) refresh(); });
// 手动更新：浏览器直接拉实时行情（腾讯行情 / Binance 公共接口），只刷新价格和涨跌，不触发 Actions。
// 四证结论按收盘计算，盘中价格只作参考，仍以最近一次收盘结论为准。
const rbtn = $('#refreshBtn'), rmsg = $('#refreshMsg');
const say = (t, c = '') => { rmsg.textContent = t; rmsg.className = 'rf-msg ' + c; };
const hhmm = () => new Date().toTimeString().slice(0, 5);
const QQ = {'^NDX': 'usNDX', '^GSPC': 'usINX', '^DJI': 'usDJI', 'CNY=X': 'whUSDCNY'};
function qqCode(sym) {
  if (QQ[sym]) return QQ[sym].startsWith('wh') ? QQ[sym] : 's_' + QQ[sym];
  let m = sym.match(/^sina:((sh|sz|bj)\d{6})$/); if (m) return 's_' + m[1];
  m = sym.match(/^csindex:(000\d{3})$/); if (m) return 's_sh' + m[1];
  m = sym.match(/^hksina:(HSI|HSTECH|HSCEI)$/); if (m) return 's_hk' + m[1];
  return null;
}
function qqLoad(codes) {  // 用 <script> 加载，不受跨域限制；返回 {code: 字段数组}
  return new Promise(res => {
    const el = document.createElement('script'); el.charset = 'gbk';
    el.src = 'https://qt.gtimg.cn/q=' + codes.join(',') + '&_=' + Date.now();
    const done = () => { const o = {}; codes.forEach(c => { const v = window['v_' + c]; if (v) o[c] = v.split('~'); }); el.remove(); res(o); };
    el.onload = done; el.onerror = done; document.head.appendChild(el);
  });
}
async function liveQuotes() {
  const items = DATA.groups.flatMap(g => g.items).filter(it => !it.error);
  const codes = [...new Set(items.map(it => qqCode(it.symbol)).filter(Boolean))];
  const q = codes.length ? await qqLoad(codes) : {}, n0 = Object.keys(q).length;
  let n = 0;
  for (const it of items) {
    const c = qqCode(it.symbol), f = c && q[c];
    let px, chg, pct;
    if (f && c.startsWith('wh')) { px = +f[3]; chg = +f[12]; pct = +f[13]; }
    else if (f) { px = +f[3]; chg = +f[4]; pct = +f[5]; }
    if (px > 0) { Object.assign(it, {close: px, chg, chg_pct: pct, live: true}); n++; }
  }
  const btc = items.find(it => it.symbol === 'BTC-USD');
  if (btc) try {
    const r = await (await fetch('https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT', {cache: 'no-store'})).json();
    Object.assign(btc, {close: +r.lastPrice, chg: +r.priceChange, chg_pct: +r.priceChangePercent, live: true}); n++;
  } catch (e) {}
  return [n, items.length, n0];
}
rbtn && (rbtn.onclick = async () => {
  if (!DATA) return;
  rbtn.disabled = true; say('正在获取实时行情…');
  try {
    await refresh();  // 先看有没有新的收盘结论发布
    const [n, total] = await liveQuotes();
    render();
    say(n ? `已更新 ${n}/${total} 个实时价 ${hhmm()}（结论仍按最近收盘）` : '实时行情暂时取不到，显示的是最近收盘数据', n ? 'ok' : 'err');
  } catch (e) { say('更新失败：' + e.message, 'err'); }
  finally { rbtn.disabled = false; }
});
})();
