/* btq 四证量化终端 front-end. Talks to the FastAPI backend (/api/*); falls back to static demo data
   (static/demo/*.json) when no backend is running, e.g. on GitHub Pages. */
(() => {
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const LC = window.LightweightCharts;
const fmt = (x, d) => x == null || isNaN(x) ? '-' : Number(x).toLocaleString('en-US', {maximumFractionDigits: d ?? (Math.abs(x) >= 1000 ? 2 : Math.abs(x) >= 1 ? 3 : 5)});
const pct = x => x == null ? '-' : (x > 0 ? '+' : '') + Number(x).toFixed(2) + '%';
const sleep = ms => new Promise(r => setTimeout(r, ms));

const S = {
  symbol: localStorage.btqSymbol || '300750.SZ', tf: '1d', preset: 'strict', period: 'short', holding: 'flat', direction: 'long',
  overrides: {}, presets: [], bars: null, analysis: null, bt: null, replay: null, demo: false, demoIndex: null,
  layers: {ma: true, fan: true, fib: true, avwap: true, structure: true, plan: true, trades: true},
  drawn: {lines: [], macdLines: [], priceLines: []}, history: [],
};

// ------------------------------------------------------------------ api with demo fallback
const demoKey = s => s.replace(/[^A-Za-z0-9._-]/g, '_');
async function api(path, body) {
  if (!S.demo) {
    let r;
    try { r = await fetch(path, body ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {}); }
    catch (e) { r = null; }
    const isJson = r && (r.headers.get('content-type') || '').includes('json');
    if (r && isJson) {
      if (r.ok) return r.json();
      const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText);
    }
    S.demo = true; toast('演示模式：静态数据，每个交易日更新。本地运行 python -m btq serve 可用全部功能');
  }
  return demoApi(path, body);
}
async function demoApi(path, body) {
  const get = async f => { const r = await fetch('static/demo/' + f); if (!r.ok) throw new Error('演示数据里没有这个标的：' + (body?.symbol || '')); return r.json(); };
  if (!S.demoIndex) S.demoIndex = await get('index.json');
  const sym = body?.symbol || new URLSearchParams(path.split('?')[1] || '').get('symbol');
  if (path.startsWith('/api/presets')) return get('presets.json');
  if (path.startsWith('/api/watchlist')) return S.demoIndex.symbols;
  if (path.startsWith('/api/scan') || path.startsWith('/api/alert')) return get('scan.json');
  if (!S.demoIndex.symbols.includes(sym)) throw new Error('演示模式只包含：' + S.demoIndex.symbols.join('、'));
  if (path.startsWith('/api/bars')) return get(demoKey(sym) + '/bars.json');
  if (path.startsWith('/api/backtest')) return get(demoKey(sym) + '/backtest.json');
  const a = await get(demoKey(sym) + '/analyze_' + (body.direction || 'long') + '.json');
  if (path.startsWith('/api/chat')) return {answer: a.interpretation, engine: 'demo'};
  return a;
}

// ------------------------------------------------------------------ charts
const base = {
  autoSize: true,
  layout: {background: {type: 'solid', color: 'transparent'}, textColor: '#a8a097', fontFamily: 'inherit'},
  grid: {vertLines: {color: 'rgba(255,255,255,0.035)'}, horzLines: {color: 'rgba(255,255,255,0.035)'}},
  rightPriceScale: {borderColor: 'rgba(255,255,255,0.08)'},
  timeScale: {borderColor: 'rgba(255,255,255,0.08)', rightOffset: 6},
  crosshair: {mode: 0, vertLine: {color: 'rgba(34,211,238,.4)', labelBackgroundColor: '#0e7490'}, horzLine: {color: 'rgba(34,211,238,.4)', labelBackgroundColor: '#0e7490'}},
  localization: {locale: 'zh-CN'},
};
const cMain = LC.createChart($('#paneMain'), base);
const sub = {...base, layout: {...base.layout, attributionLogo: false}};
const cMacd = LC.createChart($('#paneMacd'), {...sub, timeScale: {...base.timeScale, visible: false}});
const cVol = LC.createChart($('#paneVol'), sub);
const candle = cMain.addCandlestickSeries({upColor: '#ef4444', downColor: '#10b981', borderVisible: false, wickUpColor: '#ef4444', wickDownColor: '#10b981', priceLineColor: '#ef4444'});
const maColors = {5: '#e5e7eb', 10: '#facc15', 20: '#c084fc', 60: '#38bdf8'};
const maSeries = Object.fromEntries(Object.entries(maColors).map(([n, c]) => [n, cMain.addLineSeries({color: c, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false})]));
const sHist = cMacd.addHistogramSeries({priceLineVisible: false, lastValueVisible: false});
const sDif = cMacd.addLineSeries({color: '#e5e7eb', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
const sDea = cMacd.addLineSeries({color: '#38bdf8', lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
const sVol = cVol.addHistogramSeries({priceFormat: {type: 'volume'}, priceLineVisible: false, lastValueVisible: false});
const sV5 = cVol.addLineSeries({color: '#e5e7eb', lineWidth: 1, priceFormat: {type: 'volume'}, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});
const sV10 = cVol.addLineSeries({color: '#facc15', lineWidth: 1, priceFormat: {type: 'volume'}, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false});

// sync time scales + crosshair
const charts = [cMain, cMacd, cVol];
let syncing = false;
charts.forEach(c => c.timeScale().subscribeVisibleLogicalRangeChange(r => {
  if (syncing || !r) return; syncing = true;
  charts.forEach(o => { if (o === c) return; const cur = o.timeScale().getVisibleLogicalRange();
    if (!cur || Math.abs(cur.from - r.from) > 0.01 || Math.abs(cur.to - r.to) > 0.01) o.timeScale().setVisibleLogicalRange(r); });
  syncing = false;
}));

const idx = {};
function legend(t) {
  const b = S.bars; if (!b) return;
  const i = t == null ? b.candles.length - 1 : idx[t]; if (i == null) return;
  const k = b.candles[i], prev = b.candles[i - 1] || k, ch = (k.close / prev.close - 1) * 100;
  const cls = ch >= 0 ? 'pos' : 'neg';
  const ma = n => { const arr = b.ma[n]; const off = b.candles.length - arr.length; const v = arr[i - off]; return v ? fmt(v.value) : '-'; };
  $('#lgMain').innerHTML = `<b>${S.symbol}</b><span>开 <b>${fmt(k.open)}</b></span><span>高 <b>${fmt(k.high)}</b></span><span>低 <b>${fmt(k.low)}</b></span><span>收 <b class="${cls}">${fmt(k.close)}</b></span><span class="${cls}">${pct(ch)}</span>` +
    (S.layers.ma ? Object.keys(maColors).map(n => `<span style="color:${maColors[n]}">MA${n} ${ma(n)}</span>`).join('') : '');
  const g = (arr, off = 0) => arr[i - off]?.value;
  $('#lgMacd').innerHTML = `<span>MACD(12,26,9)</span><span style="color:#e5e7eb">DIF: ${fmt(g(b.dif), 3)}</span><span style="color:#38bdf8">DEA: ${fmt(g(b.dea), 3)}</span><span class="${g(b.hist) >= 0 ? 'pos' : 'neg'}">MACD: ${fmt(g(b.hist), 3)}</span>`;
  const vo = b.candles.length - b.vma5.length, vo2 = b.candles.length - b.vma10.length;
  const vf = x => x == null ? '-' : x >= 1e8 ? (x / 1e8).toFixed(2) + '亿' : x >= 1e4 ? (x / 1e4).toFixed(2) + '万' : fmt(x, 0);
  $('#lgVol').innerHTML = `<span>VOL(5,10)</span><span class="${k.close >= k.open ? 'pos' : 'neg'}">成交量: ${vf(b.volume[i].value)}</span><span style="color:#e5e7eb">MA5: ${vf(g(b.vma5, vo))}</span><span style="color:#facc15">MA10: ${vf(g(b.vma10, vo2))}</span>`;
}
charts.forEach(c => c.subscribeCrosshairMove(p => {
  legend(p.time);
  charts.forEach(o => {
    if (o === c) return;
    if (p.time) { const s = o === cMain ? candle : o === cMacd ? sDif : sVol; const v = s.data().find(x => x.time === p.time); v && v.value !== undefined ? o.setCrosshairPosition(v.value, p.time, s) : v && o.setCrosshairPosition(v.close, p.time, s); }
    else o.clearCrosshairPosition();
  });
}));

// entry-zone overlay that follows the price scale
function drawZone() {
  const z = S.analysis?.drawings?.zones?.[0], el = $('#zone');
  if (!z || !S.layers.plan) { el.style.display = 'none'; } else {
    const y1 = candle.priceToCoordinate(z.hi), y2 = candle.priceToCoordinate(z.lo);
    if (y1 == null || y2 == null) el.style.display = 'none';
    else { el.style.display = 'block'; el.firstElementChild.textContent = z.label; el.style.top = Math.min(y1, y2) + 'px'; el.style.height = Math.max(2, Math.abs(y2 - y1)) + 'px'; }
  }
  requestAnimationFrame(drawZone);
}
requestAnimationFrame(drawZone);

// ------------------------------------------------------------------ data load
async function loadBars(keepRange) {
  $('#loading').classList.remove('hidden');
  try {
    const q = `/api/bars?symbol=${encodeURIComponent(S.symbol)}&tf=${S.tf}` + (S.replay ? `&date=${S.replay.date}` : '');
    const b = await api(q);
    S.bars = b;
    b.candles.forEach((c, i) => idx[c.time] = i);
    const range = keepRange ? cMain.timeScale().getVisibleLogicalRange() : null;
    const prevN = S._prevN; S._prevN = b.candles.length;
    const ws = (b.future || []).map(time => ({time}));
    candle.setData([...b.candles, ...ws]);
    Object.entries(maSeries).forEach(([n, s]) => s.setData(S.layers.ma ? b.ma[n] : []));
    sHist.setData([...b.hist, ...ws]); sDif.setData(b.dif); sDea.setData(b.dea);
    sVol.setData([...b.volume, ...ws]); sV5.setData(b.vma5); sV10.setData(b.vma10);
    const dn = b.candles.length - (prevN || 0);
    if (range && prevN && Math.abs(dn) <= 5) charts.forEach(c => c.timeScale().setVisibleLogicalRange({from: range.from + dn, to: range.to + dn}));
    else { const n = b.candles.length; requestAnimationFrame(() => charts.forEach(c => c.timeScale().setVisibleLogicalRange({from: n - 160, to: n + 18}))); }
    legend();
    const last = b.candles.at(-1), prev = b.candles.at(-2);
    const ch = (last.close / prev.close - 1) * 100;
    $('#quote').innerHTML = `${S.symbol} <span class="${ch >= 0 ? 'up' : 'dn'}">${fmt(last.close)} ${pct(ch)}</span>`;
    $('#phMeta').textContent = `${S.tf === '1w' ? '周K' : '日K'} · ${b.last || ''}`;
    if (!S.replay) $('#rpDate').max = b.last;
    clearDrawings(); S.analysis = null;
  } catch (e) { toast(e.message); }
  finally { $('#loading').classList.add('hidden'); }
}

// ------------------------------------------------------------------ drawings
function clearDrawings() {
  S.drawn.lines.forEach(s => cMain.removeSeries(s));
  S.drawn.macdLines.forEach(s => cMacd.removeSeries(s));
  S.drawn.priceLines.forEach(p => candle.removePriceLine(p));
  S.drawn = {lines: [], macdLines: [], priceLines: []};
  candle.setMarkers(markersForTrades());
}
function layerOf(item) {
  const k = item.kind;
  if (k === 'fan') return 'fan'; if (k === 'fib') return 'fib'; if (k === 'avwap') return 'avwap';
  if (['zone', 'stop', 'target'].includes(k)) return 'plan';
  return 'structure';
}
function cleanPts(pts) {
  const m = new Map(); pts.forEach(p => p.value != null && m.set(p.time, p.value));
  return [...m.entries()].sort((a, b) => a[0] - b[0]).map(([time, value]) => ({time, value}));
}
function markersForTrades() { return S.layers.trades && S.bt ? S.bt.markers : []; }
async function render(a, animate) {
  const keep = cMain.timeScale().getVisibleLogicalRange();
  const restore = () => keep && charts.forEach(c => c.timeScale().setVisibleLogicalRange(keep));
  clearDrawings(); restore();
  const d = a.drawings;
  const items = [...d.lines.map(x => ({...x, _t: 'line'})), ...d.levels.map(x => ({...x, _t: 'level'}))];
  for (const it of items) {
    if (!S.layers[layerOf(it)]) continue;
    if (it._t === 'line') {
      const s = cMain.addLineSeries({color: it.color, lineWidth: it.width || 1, lineStyle: it.style || 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: it.kind === 'fan' || it.kind === 'trend' ? () => null : undefined, title: it.kind === 'trend' || it.kind === 'zigzag' ? it.label : ''});
      s.setData(cleanPts(it.points)); S.drawn.lines.push(s);
      if (it.macd) { const m = cMacd.addLineSeries({color: it.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false}); m.setData(cleanPts(it.macd)); S.drawn.macdLines.push(m); }
    } else {
      const title = it.kind === 'fib' ? `${it.label} · ${fmt(it.price)}` : it.label;
      S.drawn.priceLines.push(candle.createPriceLine({price: it.price, color: it.color, lineWidth: it.kind === 'stop' || it.kind === 'target' ? 2 : 1, lineStyle: it.style ?? 2, axisLabelVisible: it.kind !== 'fib', title}));
    }
    restore();
    if (animate) await sleep(45);
  }
  const mk = [...(S.layers.structure ? d.markers : []), ...markersForTrades()].sort((x, y) => x.time - y.time);
  candle.setMarkers(mk); restore();
}

// ------------------------------------------------------------------ analysis panel
function reqBody(extra) {
  return {symbol: S.symbol, tf: S.tf, preset: S.preset, overrides: S.overrides, direction: S.direction, holding: S.holding, period: S.period, date: S.replay?.date || null, ...extra};
}
async function analyze(quiet) {
  const btn = $('#btnAnalyze');
  btn.disabled = true; btn.innerHTML = '正在分析… <span class="spin" style="display:inline-block;vertical-align:middle;width:13px;height:13px"></span>';
  const sc = $('#stepsCard'); sc.classList.remove('hidden');
  const names = [['识别图表结构', '结构线 · 历史数据回测'], ['计算规则信号', '四证逐条判定'], ['在图上划线', '逐条画出'], ['AI 深度解读', '含在本次分析内']];
  $('#steps').innerHTML = names.map(([n, d], i) => `<div class="step" id="st${i}"><span class="st"></span><div><b>${n}</b><span class="muted xs">${d}</span></div><span class="t"></span></div>`).join('');
  $('#stepsTitle').textContent = '正在分析'; const t0 = performance.now();
  try {
    const pending = api('/api/analyze', reqBody());
    if (!quiet) for (let i = 0; i < 2; i++) { $('#st' + i).classList.add('run'); await sleep(260); }
    const a = await pending; S.analysis = a;
    a.steps.forEach((s, i) => { const el = $('#st' + i); el.classList.remove('run'); if (i < 2) { el.classList.add('done'); el.querySelector('.st').textContent = '✓'; el.querySelector('.muted').textContent = s.desc; el.querySelector('.t').textContent = s.sec + ' 秒'; } });
    $('#st2').classList.add('run');
    await render(a, !quiet);
    const s2 = $('#st2'); s2.classList.replace('run', 'done'); s2.querySelector('.st').textContent = '✓'; s2.querySelector('.muted').textContent = a.steps[2].desc;
    $('#st3').classList.add('run'); if (!quiet) await sleep(220);
    showScores(a); showSignal(a);
    const s3 = $('#st3'); s3.classList.replace('run', 'done'); s3.querySelector('.st').textContent = '✓';
    $('#stepsTitle').textContent = '分析完成'; $('#stepsTime').textContent = ((performance.now() - t0) / 1000).toFixed(1) + ' 秒';
  } catch (e) { toast(e.message); $('#stepsTitle').textContent = '分析失败'; }
  finally { btn.disabled = false; btn.innerHTML = '✦ AI 分析当前图表'; }
}
function gauge(v) {
  const cx = 100, cy = 100, r = 78, ang = x => Math.PI * (1 - (x + 100) / 200);
  const pt = x => [cx + r * Math.cos(ang(x)), cy - r * Math.sin(ang(x))];
  const arc = (a, b, c) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `<path d="M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}" stroke="${c}" stroke-width="12" fill="none" stroke-linecap="round"/>`; };
  const [nx, ny] = [cx + (r - 18) * Math.cos(ang(v)), cy - (r - 18) * Math.sin(ang(v))];
  $('#gauge').innerHTML = `<defs><linearGradient id="gg" x1="0" x2="1"><stop offset="0" stop-color="#ef4444"/><stop offset=".5" stop-color="#facc15"/><stop offset="1" stop-color="#10b981"/></linearGradient></defs>` +
    `<path d="M${pt(-100)[0]} ${pt(-100)[1]} A${r} ${r} 0 0 1 ${pt(100)[0]} ${pt(100)[1]}" stroke="url(#gg)" stroke-width="12" fill="none" stroke-linecap="round" opacity=".9"/>` +
    `<line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="#e7e2da" stroke-width="3" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="6" fill="#e7e2da"/>`;
}
function showScores(a) {
  const s = a.scores; $('#scoreCard').classList.remove('hidden');
  gauge(s.composite);
  const col = s.composite >= 20 ? '#f87171' : s.composite <= -20 ? '#34d399' : '#facc15';
  $('#gaugeVal').textContent = (s.composite > 0 ? '+' : '') + s.composite; $('#gaugeVal').style.color = col;
  $('#gaugeLbl').textContent = s.bias; $('#gaugeLbl').style.color = col;
  $('#bias').textContent = s.bias; $('#bias').style.cssText = `color:${col};background:${col}22`;
  $('#scoreSub').textContent = `${S.tf === '1w' ? '周线' : '日线'} · ${a.date} · ${a.period.name}`;
  $('#scoreBars').innerHTML = s.items.map(i => {
    const w = Math.abs(i.score) / 2, left = i.score >= 0 ? 50 : 50 - w, c = i.score >= 0 ? '#f87171' : '#34d399';
    return `<div class="bar"><div class="bh"><span>${i.name}</span><span style="color:${c}">${i.score > 0 ? '+' : ''}${i.score}</span></div><div class="tr"><i style="left:${left}%;width:${w}%;background:${c}"></i></div><div class="d">${i.desc}</div></div>`;
  }).join('');
}
function showSignal(a) {
  const p = a.plan; $('#signalCard').classList.remove('hidden');
  $('#sigModel').textContent = `◎ ${a.model} · ${p.model}`;
  const v = $('#verdict'); v.textContent = p.verdict; v.className = 'verdict ' + p.tone;
  $('#sigTags').innerHTML = `<span class="acc">${a.direction === 'long' ? '↗ 做多' : '↘ 做空'}</span><span>◷ ${a.period.name} · ${a.period.bars} 日</span><span class="acc">证据 ${p.score}/4</span><span>反向 ${p.opposite_score}/4</span>` + (S.replay ? `<span>回放 ${a.date}</span>` : '');
  $('#sigText').textContent = a.interpretation;
  const ai = $('#sigAi'); if (a.interpretation_ai) { ai.textContent = 'AI：' + a.interpretation_ai; ai.classList.remove('hidden'); } else ai.classList.add('hidden');
  const up = a.direction === 'long';
  $('#metrics').innerHTML = [
    ['现价', fmt(p.price), a.date],
    ['入场区间', `${fmt(p.entry[0])} - ${fmt(p.entry[1])}`, `中值 ${pct(p.entry_mid_dist)} · 距现价`, 'wide', '#22d3ee'],
    ['止损', fmt(p.stop), `${pct(p.stop_dist)} · 距现价`, '', '#f87171'],
    ['第一目标', fmt(p.targets[0]), `${pct(p.target_dist[0])} · 距现价`, '', '#34d399'],
    ['盈亏比', p.rr ? p.rr.toFixed(2) + ' : 1' : '-', '按入场中值'],
    ['第二目标', fmt(p.targets[1]), `${pct(p.target_dist[1])} · 距现价`, '', '#34d399'],
  ].map(([k, val, d, cls, c]) => `<div class="metric ${cls || ''}"><div class="k">${k}</div><div class="v" style="${c ? 'color:' + c : ''}">${val}</div><div class="d">${d}</div></div>`).join('');
  const ev = (e, title) => `<div><div class="eh">${title} ${e.score}/4 ${e.fired ? '<span class="pill b4">成立</span>' : ''}</div><ul>${e.items.map(i => `<li class="${i.ok ? 'ok' : 'no'}"><i>${i.ok ? '✓' : '·'}</i><div>${i.name}${i.detail ? `<small>${i.detail}</small>` : ''}</div></li>`).join('')}</ul></div>`;
  $('#evidence').innerHTML = ev(a.evidence.bottom, '抄底四证') + ev(a.evidence.top, '逃顶四证');
}

// ------------------------------------------------------------------ backtest
let eqChart, eqS, bhS;
async function backtest() {
  const dr = $('#drawer'); dr.classList.remove('hidden'); $('#btnBacktest').classList.add('on');
  $('#btTitle').textContent = `回测 · ${S.symbol}`; $('#btSub').textContent = '计算中…';
  try {
    const r = await api('/api/backtest', reqBody({date: null})); S.bt = r;
    const m = r.metrics;
    $('#btSub').textContent = `${r.model} · ${m.start} 至 ${m.end} · 佣金和滑点各 0.05%`;
    const P = x => x == null ? '-' : (x * 100).toFixed(1) + '%';
    $('#btMetrics').innerHTML = [['策略收益', P(m.total_return)], ['买入持有', P(m.buy_and_hold)], ['年化', P(m.cagr)], ['最大回撤', P(m.max_drawdown)], ['夏普', m.sharpe], ['交易笔数', m.trades], ['胜率', m.win_rate == null ? '-' : P(m.win_rate)], ['盈亏因子', m.profit_factor]]
      .map(([k, v]) => `<div class="metric"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
    if (!eqChart) {
      eqChart = LC.createChart($('#btEquity'), {...base, rightPriceScale: {mode: 0, borderColor: 'rgba(255,255,255,0.08)'}, timeScale: {borderColor: 'rgba(255,255,255,0.08)', minBarSpacing: 0.02, tickMarkFormatter: t => { const d = new Date(t * 1000); return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0'); }}});
      eqS = eqChart.addAreaSeries({lineColor: '#22d3ee', topColor: 'rgba(34,211,238,.25)', bottomColor: 'rgba(34,211,238,0)', lineWidth: 2, title: '策略'});
      bhS = eqChart.addLineSeries({color: 'rgba(231,226,218,.45)', lineWidth: 1, title: '买入持有'});
    }
    const rel = arr => { const b0 = arr[0]?.value || 1; return arr.map(p => ({time: p.time, value: +((p.value / b0 - 1) * 100).toFixed(2)})); };
    eqS.setData(rel(r.equity)); bhS.setData(rel(r.buyhold));
    eqS.applyOptions({priceFormat: {type: 'custom', formatter: v => v.toFixed(1) + '%'}}); bhS.applyOptions({priceFormat: {type: 'custom', formatter: v => v.toFixed(1) + '%'}});
    const fit = () => eqChart.timeScale().setVisibleLogicalRange({from: 0, to: r.equity.length - 1}); fit(); setTimeout(fit, 120); setTimeout(fit, 600);
    $('#btBody').innerHTML = r.episodes.map(e => `<tr><td>${e.episode}</td><td>${e.side === 'long' ? '多' : '空'}</td><td>${String(e.entry_date).slice(0, 10)}</td><td>${e.exit_date ? String(e.exit_date).slice(0, 10) : '持仓中'}</td><td class="${e.ret > 0 ? 'pos' : 'neg'}">${e.ret == null ? '-' : (e.ret * 100).toFixed(1) + '%'}</td><td>${e.bars}</td><td>${e.exit_reason || ''}</td></tr>`).join('') || '<tr><td colspan="7" class="muted">这段时间四证一次都没齐，没有交易。</td></tr>';
    if (S.analysis) render(S.analysis, false); else candle.setMarkers(markersForTrades());
  } catch (e) { toast(e.message); $('#btSub').textContent = '回测失败'; }
}

// ------------------------------------------------------------------ replay
let playTimer = null;
async function replayTo(date) {
  S.replay = {date}; await loadBars(true); await analyze(true);
  $('#rpInfo').textContent = `${S.replay.date} · 第 ${S.bars.candles.length} / ${S.bars.n} 根`;
}
async function replayStep(dir) {
  if (!S.replay) return;
  const full = S._full; const cur = full.findIndex(t => t >= S.replay.date);
  const j = Math.max(0, Math.min(full.length - 1, (cur < 0 ? full.length - 1 : cur) + dir));
  $('#rpDate').value = full[j]; await replayTo(full[j]);
  if (j === full.length - 1) stopPlay();
}
function stopPlay() { clearInterval(playTimer); playTimer = null; $('#rpPlay').textContent = '▶'; }

// ------------------------------------------------------------------ chat
function addMsg(text, who) { const el = document.createElement('div'); el.className = 'msg ' + who; el.textContent = text; $('#chatLog').appendChild(el); el.scrollIntoView({block: 'end'}); return el; }
async function ask(q) {
  if (!q.trim()) return; addMsg(q, 'me'); const w = addMsg('思考中…', 'bot');
  try {
    const r = await api('/api/chat', reqBody({question: q, history: S.history}));
    w.textContent = r.answer; $('#chatEngine').textContent = r.engine === 'llm' ? '由大模型回答（BTQ_LLM_* 已配置）' : '由规则引擎回答 · 配置 BTQ_LLM_API_KEY 可接入大模型';
    S.history.push({role: 'user', content: q}, {role: 'assistant', content: r.answer});
  } catch (e) { w.textContent = '出错了：' + e.message; }
}

// ------------------------------------------------------------------ model tab
const PARAMS = [
  ['signal', 'volume_window', '地量/天量窗口（日）'], ['signal', 'reclaim_vol_mult', '放量倍数'], ['signal', 'vol_avg_window', '均量天数'],
  ['signal', 'fan_ratio', '速度扇比例'], ['signal', 'min_wave_move', '抄底波段最小跌幅'], ['top', 'min_wave_move', '逃顶波段最小涨幅'],
  ['risk', 'stop_below_low', '止损（低点下方）'], ['risk', 'initial_frac', '首次仓位'], ['risk', 'trail_after_tp', '移动止盈'], ['risk', 'allow_short', '允许做空 (true/false)'],
];
function renderPresets() {
  $('#preset').innerHTML = S.presets.map(p => `<option value="${p.key}">${p.name}</option>`).join(''); $('#preset').value = S.preset;
  $('#presetCards').innerHTML = S.presets.map(p => `<div class="card preset ${p.key === S.preset ? 'on' : ''}" data-k="${p.key}"><b>${p.name}</b><div class="muted s">${p.desc}</div></div>`).join('');
  $$('#presetCards .preset').forEach(el => el.onclick = () => { S.preset = el.dataset.k; S.overrides = {}; renderPresets(); });
  const cur = S.presets.find(p => p.key === S.preset)?.params; if (!cur) return;
  $('#params').innerHTML = PARAMS.map(([sec, k, lbl]) => `<label>${lbl}<input data-sec="${sec}" data-k="${k}" value="${S.overrides[sec]?.[k] ?? cur[sec][k]}"></label>`).join('');
  $$('#params input').forEach(inp => inp.onchange = () => { const {sec, k} = inp.dataset; (S.overrides[sec] ||= {})[k] = inp.value; });
}

// ------------------------------------------------------------------ tasks tab
async function scan() {
  $('#scanInfo').textContent = '扫描中…'; $('#btnScan').disabled = true;
  try {
    const syms = $('#watch').value.split(/\n|,/).map(s => s.trim()).filter(Boolean);
    const rows = await api('/api/scan', {symbols: syms, preset: S.preset, tf: S.tf});
    const pill = (v, f, side) => `<span class="pill ${f ? (side === 'b' ? 'b4' : 't4') : v >= 3 ? 'p3' : ''}">${v}/4</span>`;
    $('#scanBody').innerHTML = rows.map(r => r.error ? `<tr><td>${r.symbol}</td><td colspan="4" class="muted">${r.error.slice(0, 40)}</td></tr>` :
      `<tr data-s="${r.symbol}"><td><b>${r.symbol}</b></td><td>${fmt(r.price)} <span class="${r.change_pct >= 0 ? 'pos' : 'neg'} xs">${pct(r.change_pct)}</span></td><td>${pill(r.bottom, r.bottom_fired, 'b')}</td><td>${pill(r.top, r.top_fired, 't')}</td><td class="${r.composite >= 0 ? 'pos' : 'neg'}">${r.composite}</td></tr>`).join('');
    $$('#scanBody tr[data-s]').forEach(tr => tr.onclick = () => setSymbol(tr.dataset.s));
    $('#scanInfo').textContent = `${rows.length} 个标的 · ${rows[0]?.date || ''}`;
  } catch (e) { toast(e.message); $('#scanInfo').textContent = ''; }
  finally { $('#btnScan').disabled = false; }
}

// ------------------------------------------------------------------ wiring
async function setSymbol(s) {
  S.symbol = s.trim().toUpperCase().replace(/^(AKSHARE|CCXT|CSV|YAHOO):/, m => m.toLowerCase()); localStorage.btqSymbol = S.symbol;
  $('#symbol').value = S.symbol; S.bt = null; S.replay = null; $('#replaybar').classList.add('hidden'); $('#drawer').classList.add('hidden');
  ['#scoreCard', '#signalCard', '#stepsCard'].forEach(x => $(x).classList.add('hidden'));
  await loadBars(); analyze();
}
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.remove('hidden'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add('hidden'), 4200); }
const seg = (sel, cb) => $$(sel + ' button').forEach(b => b.onclick = () => { $$(sel + ' button').forEach(x => x.classList.remove('on')); b.classList.add('on'); cb(b.dataset.v); });

$('#symbol').addEventListener('keydown', e => e.key === 'Enter' && setSymbol(e.target.value));
$('#symbol').addEventListener('change', e => e.target.value.toUpperCase() !== S.symbol && setSymbol(e.target.value));
seg('#tf', v => { S.tf = v; loadBars().then(() => analyze(true)); });
seg('#direction', v => { S.direction = v; analyze(); });
$('#preset').onchange = e => { S.preset = e.target.value; S.overrides = {}; renderPresets(); analyze(); };
$('#period').onchange = e => { S.period = e.target.value; analyze(true); };
$('#holding').onchange = e => { S.holding = e.target.value; analyze(true); };
$('#btnAnalyze').onclick = () => analyze();
$('#btnBacktest').onclick = () => $('#drawer').classList.contains('hidden') ? backtest() : ($('#drawer').classList.add('hidden'), $('#btnBacktest').classList.remove('on'));
$('#btClose').onclick = () => { $('#drawer').classList.add('hidden'); $('#btnBacktest').classList.remove('on'); };
$('#btnRunBt').onclick = () => backtest();
$('#btnReset').onclick = () => { S.overrides = {}; renderPresets(); };
$('#btnLayers').onclick = () => { $('#layers').classList.toggle('hidden'); $('#btnLayers').classList.toggle('on'); };
$$('#layers input').forEach(i => i.onchange = () => { S.layers[i.dataset.layer] = i.checked; Object.entries(maSeries).forEach(([n, s]) => s.setData(S.layers.ma ? S.bars.ma[n] : [])); S.analysis ? render(S.analysis, false) : candle.setMarkers(markersForTrades()); legend(); });
$('#btnPanel').onclick = () => $('#panel').classList.toggle('hidden');
$('#btnClose').onclick = () => $('#panel').classList.add('hidden');
$$('.tabs button').forEach(b => b.onclick = () => { $$('.tabs button').forEach(x => x.classList.remove('on')); b.classList.add('on'); $$('.tab').forEach(t => t.classList.add('hidden')); $('#tab-' + b.dataset.tab).classList.remove('hidden'); });
$('#chatForm').onsubmit = e => { e.preventDefault(); const q = $('#chatInput').value; $('#chatInput').value = ''; ask(q); };
$$('#quick button').forEach(b => b.onclick = () => ask(b.textContent));
$('#btnScan').onclick = scan;
$('#btnSaveWatch').onclick = async () => { const syms = $('#watch').value.split(/\n|,/).map(s => s.trim()).filter(Boolean); try { await api('/api/watchlist', {symbols: syms}); toast('自选已保存'); } catch (e) { toast(e.message); } };
$('#btnAlert').onclick = async () => {
  const syms = $('#watch').value.split(/\n|,/).map(s => s.trim()).filter(Boolean);
  $('#alertInfo').textContent = '扫描中…';
  try { const r = await api('/api/alert', {symbols: syms, preset: S.preset, webhook: $('#webhook').value.trim(), min_score: +$('#minScore').value});
    $('#alertInfo').textContent = r.hits ? (r.hits.length ? r.hits.join('\n') + (r.sent ? '\n已推送 ✓' : '\n（未填 webhook，只显示不推送）') : '没有达到阈值的标的。') : '演示模式不支持推送';
  } catch (e) { $('#alertInfo').textContent = '失败：' + e.message; }
};
$('#btnReplay').onclick = () => {
  if (S.demo) return toast('回放需要本地后端：python -m btq serve');
  const bar = $('#replaybar'); bar.classList.toggle('hidden'); $('#btnReplay').classList.toggle('on');
  if (!bar.classList.contains('hidden')) {
    S._full = S.bars.candles.map(c => new Date(c.time * 1000).toISOString().slice(0, 10));
    const start = S._full[Math.max(0, S._full.length - 120)]; $('#rpDate').min = S._full[80]; $('#rpDate').value = start; replayTo(start);
  } else { stopPlay(); S.replay = null; loadBars(true).then(() => analyze(true)); }
};
$('#rpDate').onchange = e => { if (S.replay?.date !== e.target.value) replayTo(e.target.value); };
$('#rpPrev').onclick = () => replayStep(-1);
$('#rpNext').onclick = () => replayStep(1);
$('#rpPlay').onclick = () => {
  if (playTimer) return stopPlay();
  $('#rpPlay').textContent = '⏸';
  let busy = false;
  playTimer = setInterval(async () => { if (busy) return; busy = true; await replayStep(1); busy = false; }, +$('#rpSpeed').value);
};
$('#rpExit').onclick = () => $('#btnReplay').click();
setInterval(() => $('#clock').textContent = new Date().toLocaleTimeString('zh-CN', {hour12: false}) + ' UTC' + (-(new Date().getTimezoneOffset() / 60) >= 0 ? '+' : '') + (-(new Date().getTimezoneOffset() / 60)), 1000);

// boot
(async () => {
  try { S.presets = await api('/api/presets'); renderPresets(); } catch (e) { toast(e.message); }
  try { const w = await api('/api/watchlist'); $('#watch').value = w.join('\n'); $('#symlist').innerHTML = w.map(s => `<option value="${s}">`).join('');
    if (S.demo && !S.demoIndex.symbols.includes(S.symbol)) S.symbol = S.demoIndex.symbols[0];
  } catch (e) {}
  $('#symbol').value = S.symbol;
  await loadBars(); analyze();
})();
})();
