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
  const r = await fetch('static/demo/overview.json', {cache: 'no-cache'});
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
})();
