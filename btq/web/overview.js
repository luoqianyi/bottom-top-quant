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
    ${it.live ? `<span class="lv${it.est ? ' est' : ''}" title="${it.est ? '用跟踪ETF的涨跌幅估算；' : ''}获取时间（北京时间），结论仍按最近收盘">${it.est ? '估 ' : ''}${it.ts}</span>` : ''}
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
// 实时源（全部可在浏览器跨域加载）：腾讯 qt.gtimg.cn（A股/港股/美股指数、海外指数 gz*、外盘期货 hf_*、外汇 wh*）、
// 新浪期货分时 jsonp（小纳指、A50）、东方财富 jsonp（中证2000、恒生医疗、金交所Au99.99、印度SENSEX）、Binance（BTC）
const QQ = {'^NDX': 's_usNDX', '^GSPC': 's_usINX', '^DJI': 's_usDJI', 'CNY=X': 'whUSDCNY', 'DX-Y.NYB': 'whUSDX',
  '^N225': 'gzN225', '^KS11': 'gzKS11', '^TWII': 'gzTWII', '^GDAXI': 'gzGDAXI', '^FTSE': 'gzFTSE', 'GC=F': 'hf_GC', 'CL=F': 'hf_CL'};
const SINA_MIN = {'NQ=F': 'NQ', 'sinafut:CHA50CFD': 'CHA50CFD'};
const EM = {'csindex:932000': '2.932000', 'hksina:HSHCI': '124.HSHCI', 'sge:Au99.99': '118.AU9999', '^BSESN': '100.SENSEX'};
const EST = {'csindex:932000': 's_sh563300', 'sge:Au99.99': 's_sh518880'};  // 东财取不到时用跟踪 ETF 的涨跌幅估算
function qqCode(sym) {
  if (QQ[sym]) return QQ[sym];
  let m = sym.match(/^sina:((sh|sz|bj)\d{6})$/); if (m) return 's_' + m[1];
  m = sym.match(/^csindex:(000\d{3})$/); if (m) return 's_sh' + m[1];
  m = sym.match(/^hksina:(HSI|HSTECH|HSCEI)$/); if (m) return 's_hk' + m[1];
  return null;
}
function qqParse(c, v) {
  const f = v.split(c.startsWith('hf_') ? ',' : '~');
  if (c.startsWith('hf_')) { const px = +f[0], pre = +f[7]; return [px, px - pre, +f[1]]; }
  if (c.startsWith('wh')) return [+f[3], +f[12], +f[13]];
  return [+f[3], +f[4], +f[5]];  // s_*、gz* 都是 价格~涨跌~涨跌幅
}
function script(src, charset, ms = 6000) {  // 加载跨域脚本，超时或出错都当作没取到
  return new Promise(res => {
    const el = document.createElement('script'); if (charset) el.charset = charset; el.src = src;
    const t = setTimeout(() => fin(false), ms), fin = ok => { clearTimeout(t); el.remove(); res(ok); };
    el.onload = () => fin(true); el.onerror = () => fin(false); document.head.appendChild(el);
  });
}
async function qqLoad(codes) {
  if (!codes.length) return {};
  await script('https://qt.gtimg.cn/q=' + codes.join(',') + '&_=' + Date.now(), 'gbk');
  const o = {}; codes.forEach(c => { const v = window['v_' + c]; if (v) o[c] = qqParse(c, v); }); return o;
}
async function sinaMin(code) {
  const v = '_btq' + code;
  await script(`https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20${v}=/GlobalFuturesService.getGlobalFuturesMinLine?symbol=${code}&_=${Date.now()}`);
  const rows = window[v] && window[v].minLine_1d; if (!rows || !rows.length) return null;
  const pre = +rows[0][1], px = +rows.at(-1)[rows.length > 1 ? 1 : 5];
  return pre > 0 && px > 0 ? [px, px - pre, (px / pre - 1) * 100] : null;
}
async function emLoad(secids) {
  if (!secids.length) return {};
  let got = null; window.btqEM = d => { got = d; };
  await script('https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&fields=f2,f3,f4,f12,f13&cb=btqEM&secids=' + secids.join(',') + '&_=' + Date.now());
  const o = {}; ((got && got.data && got.data.diff) || []).forEach(x => { if (typeof x.f2 === 'number') o[x.f13 + '.' + x.f12] = [x.f2, x.f4, x.f3]; });
  return o;
}
const stamp = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(5, 16).replace('T', ' ');  // 北京时间 MM-DD HH:mm
const today = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(0, 10);  // 北京时间日期
async function liveQuotes() {
  const items = DATA.groups.flatMap(g => g.items).filter(it => !it.error);
  const has = m => items.filter(it => m[it.symbol]);
  const codes = [...new Set([...items.map(it => qqCode(it.symbol)), ...has(EST).map(it => EST[it.symbol])].filter(Boolean))];
  const [q, em, mins, btc] = await Promise.all([
    qqLoad(codes), emLoad(has(EM).map(it => EM[it.symbol])),
    Promise.all(has(SINA_MIN).map(async it => [it.symbol, await sinaMin(SINA_MIN[it.symbol])])),
    fetch('https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT', {cache: 'no-store'}).then(r => r.json()).catch(() => null)]);
  const live = Object.fromEntries(mins.filter(x => x[1]));
  if (btc && +btc.lastPrice > 0) live['BTC-USD'] = [+btc.lastPrice, +btc.priceChange, +btc.priceChangePercent];
  let n = 0;
  for (const it of items) {
    let v = live[it.symbol] || (qqCode(it.symbol) && q[qqCode(it.symbol)]) || (EM[it.symbol] && em[EM[it.symbol]]), est = false;
    if (!v && EST[it.symbol] && q[EST[it.symbol]] && it.date < today() && !it.live) {  // 只在还没有今天收盘数据时估算
      const pct = q[EST[it.symbol]][2], px = it.close * (1 + pct / 100); v = [px, px - it.close, pct]; est = true;
    }
    if (v && v[0] > 0 && isFinite(v[1]) && isFinite(v[2])) { Object.assign(it, {close: v[0], chg: v[1], chg_pct: v[2], live: true, est, ts: stamp()}); n++; }
  }
  return [n, items.length];
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
