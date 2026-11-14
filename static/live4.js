// 盘中预估：把 btq/signals.py 的四证（抄底 / 逃顶）和 overview.verdict 原样搬到浏览器里。
// 输入是最近 N 根日线 + 用实时价拼出来的“今天”这一根，输出 入场 / 离场 / 减仓 / 关注 / 观望。
(function (root) {
'use strict';
function ema(a, n) { const k = 2 / (n + 1), o = new Array(a.length); let p = a[0]; for (let i = 0; i < a.length; i++) { p = i ? a[i] * k + p * (1 - k) : a[0]; o[i] = p; } return o; }
function rolling(a, n, f) { const o = new Array(a.length).fill(NaN); for (let i = n - 1; i < a.length; i++) { let r = f === 'min' ? Infinity : -Infinity; for (let j = i - n + 1; j <= i; j++) r = f === 'min' ? Math.min(r, a[j]) : Math.max(r, a[j]); o[i] = r; } return o; }
function pivots(s, k, kind) {
  const out = [];
  for (let p = k; p < s.length - k; p++) {
    let ext = s[p - k], at = 0;
    for (let j = 0; j <= 2 * k; j++) { const v = s[p - k + j]; if (kind === 'low' ? v < ext : v > ext) { ext = v; at = j; } }
    if (s[p] === ext && at === k) out.push([p, s[p], p + k]);
  }
  return out;
}
function fan(p0, i0, p1, i1, ratio, i) { if (i1 === i0) return NaN; const tg = p0 + (p1 - p0) * ratio; return p0 + (tg - p0) / (i1 - i0) * (i - i0); }
const argOf = (a, lo, hi, kind) => { let b = lo; for (let j = lo; j <= hi; j++) if (kind === 'max' ? a[j] > a[b] : a[j] < a[b]) b = j; return b; };
const maxOf = (a, lo, hi) => { let m = -Infinity; for (let j = lo; j <= hi; j++) m = Math.max(m, a[j]); return m; };
const minOf = (a, lo, hi) => { let m = Infinity; for (let j = lo; j <= hi; j++) m = Math.min(m, a[j]); return m; };

function Engine(bars, cfg) {
  const S = cfg.signal;
  this.cfg = cfg; this.o = bars.o; this.h = bars.h; this.l = bars.l; this.c = bars.c; this.v = bars.v;
  const ef = ema(this.c, S.macd_fast), es = ema(this.c, S.macd_slow);
  this.dif = ef.map((x, i) => x - es[i]);
  this.vmin = rolling(this.v, S.volume_window, 'min'); this.vmax = rolling(this.v, S.volume_window, 'max');
  const n5 = S.vol_avg_window; this.vavg = new Array(this.v.length).fill(NaN);
  for (let i = n5; i < this.v.length; i++) { let s = 0; for (let j = i - n5; j < i; j++) s += this.v[j]; this.vavg[i] = s / n5; }
  this.pivLo = pivots(this.l, S.pivot_k, 'low'); this.pivHi = pivots(this.h, S.pivot_k, 'high');
  this.waveLo = pivots(this.l, S.wave_pivot_k, 'low'); this.waveHi = pivots(this.h, S.wave_pivot_k, 'high');
  this.hasVol = this.v.reduce((a, b) => a + (b || 0), 0) > 0; this._aw = {};
}
Engine.prototype.avwap = function (a) {
  if (this._aw[a]) return this._aw[a];
  const o = new Array(this.c.length).fill(NaN); let pv = 0, vv = 0;
  for (let i = a; i < this.c.length; i++) { const tp = (this.h[i] + this.l[i] + this.c[i]) / 3; pv += tp * this.v[i]; vv += this.v[i]; o[i] = vv > 0 ? pv / vv : tp; }
  return (this._aw[a] = o);
};
Engine.prototype.cluster = function (hits) {
  if (!hits.length) return null; const gap = this.cfg.signal.cluster_gap; let st = hits[hits.length - 1];
  for (let i = hits.length - 1; i > 0; i--) { if (hits[i] - hits[i - 1] <= gap) st = hits[i - 1]; else break; }
  return st;
};
Engine.prototype.waveStart = function (t, lo, kind) {
  const piv = kind === 'high' ? this.waveHi : this.waveLo;
  const glob = kind === 'high' ? argOf(this.h, lo, t, 'max') : argOf(this.l, lo, t, 'min');
  const set = new Set(piv.filter(p => lo <= p[0] && p[0] <= t && p[2] <= t).map(p => p[0])); set.add(glob);
  const cands = [...set].sort((a, b) => b - a);
  const need = kind === 'high' ? this.cfg.signal.min_wave_move : this.cfg.top.min_wave_move;
  for (const p of cands) {
    if (kind === 'high') { if (this.h[p] < maxOf(this.h, p, t)) continue; if (1 - minOf(this.l, p, t) / this.h[p] >= need) return p; }
    else { if (this.l[p] > minOf(this.l, p, t)) continue; if (maxOf(this.h, p, t) / this.l[p] - 1 >= need) return p; }
  }
  return glob;
};
Engine.prototype.bottom = function (t) {
  const S = this.cfg.signal, ev = {e: [false, false, false, false], wave_ok: false, stop: NaN};
  const lo = Math.max(0, t - S.wave_lookback); if (t - lo < S.volume_window) return ev;
  const iH = this.waveStart(t, lo, 'high'), PH = this.h[iH]; if (t - iH < S.min_wave_bars) return ev;
  const iL = argOf(this.l, iH, t, 'min'), PL = this.l[iL];
  ev.wave_ok = 1 - PL / PH >= S.min_wave_move;
  let anchor = null;
  if (this.hasVol) { const hits = []; for (let j = iH + 1; j <= t; j++) if (!isNaN(this.vmin[j]) && this.v[j] > 0 && this.v[j] <= this.vmin[j] * (1 + 1e-9)) hits.push(j); anchor = this.cluster(hits); }
  ev.e[0] = anchor !== null;
  const pl = this.pivLo.filter(p => iH <= p[0] && p[0] <= t && p[2] <= t);
  const p2 = [...pl].reverse().find(p => p[1] <= PL * (1 + S.low_tolerance));
  if (p2) { const prev = pl.filter(p => p[0] <= p2[0] - S.min_pivot_gap && p[1] > p2[1]); if (prev.length && this.dif[p2[0]] > this.dif[prev[prev.length - 1][0]]) ev.e[1] = true; }
  if (t - iL > S.max_bars_from_extreme) ev.wave_ok = false;
  if (t > iL) ev.e[2] = this.c[t] > fan(PH, iH, PL, iL, S.fan_ratio, t);
  if (anchor !== null) {
    const aw = this.avwap(anchor);
    if (this.c[t] > aw[t]) {
      let j0 = t; while (j0 - 1 > anchor && this.c[j0 - 1] > aw[j0 - 1] * (1 + S.reclaim_tolerance)) j0--;
      for (let j = j0; j <= Math.min(t, j0 + S.confirm_window - 1); j++) { const ok = this.vavg[j] > 0 && this.v[j] >= S.reclaim_vol_mult * this.vavg[j]; if (this.c[j] > aw[j] && ok) { ev.e[3] = true; break; } }
    }
  }
  ev.stop = PL * (1 - this.cfg.risk.stop_below_low);
  return ev;
};
Engine.prototype.top = function (t) {
  const S = this.cfg.signal, T = this.cfg.top, ev = {e: [false, false, false, false], wave_ok: false};
  const lo = Math.max(0, t - S.wave_lookback); if (t - lo < S.volume_window) return ev;
  const iL = this.waveStart(t, lo, 'low'), PL = this.l[iL]; if (t - iL < S.min_wave_bars) return ev;
  const iH = argOf(this.h, iL, t, 'max'), PH = this.h[iH];
  ev.wave_ok = PH / PL - 1 >= T.min_wave_move;
  let anchor = null;
  if (this.hasVol) { const hits = []; for (let j = iL + 1; j <= t; j++) if (!isNaN(this.vmax[j]) && this.v[j] >= this.vmax[j] * (1 - 1e-9)) hits.push(j); anchor = this.cluster(hits); }
  const ph = this.pivHi.filter(p => iL <= p[0] && p[0] <= t && p[2] <= t);
  let shrink = false;
  if (ph.length >= 2 && this.hasVol) { const a = ph[ph.length - 1], b = ph[ph.length - 2]; shrink = a[1] > b[1] && this.v[a[0]] < this.v[b[0]]; }
  ev.e[0] = anchor !== null || (T.accept_volume_divergence && shrink);
  if (anchor === null && shrink) anchor = ph[ph.length - 1][0];
  const p2 = [...ph].reverse().find(p => p[1] >= PH * (1 - S.low_tolerance));
  if (p2) { const prev = ph.filter(p => p[0] <= p2[0] - S.min_pivot_gap && p[1] < p2[1]); if (prev.length && this.dif[p2[0]] < this.dif[prev[prev.length - 1][0]]) ev.e[1] = true; }
  if (t - iH > S.max_bars_from_extreme) ev.wave_ok = false;
  if (t > iH) { ev.f05 = fan(PL, iL, PH, iH, S.fan_ratio, t); ev.e[2] = this.c[t] < ev.f05; }
  if (anchor !== null) {
    const aw = this.avwap(anchor); ev.aw = aw[t];
    if (this.c[t] < aw[t]) {
      let j0 = t; while (j0 - 1 > anchor && this.c[j0 - 1] < aw[j0 - 1] * (1 - S.reclaim_tolerance)) j0--;
      for (let j = j0; j <= Math.min(t, j0 + S.confirm_window - 1); j++) { const ok = T.break_vol_mult <= 0 || (this.vavg[j] > 0 && this.v[j] >= T.break_vol_mult * this.vavg[j]); if (this.c[j] < aw[j] && ok) { ev.e[3] = true; break; } }
    }
  }
  return ev;
};
const NB = ['地量', '底背离', '跌速放缓', '成本线'], NT = ['天量 / 量价背离', '顶背离', '涨速衰竭', '跌破成本线'];
function verdict(b, t) {
  const bs = b.e.filter(Boolean).length, ts = t.e.filter(Boolean).length;
  const tn = NT.filter((_, i) => t.e[i]), bn = NB.filter((_, i) => b.e[i]);
  if (b.wave_ok && bs === 4) return ['入场', 'go', '抄底四证齐全' + (b.stop ? '，止损 ' + b.stop.toLocaleString('en', {maximumFractionDigits: 2}) : ''), bs, ts];
  if (t.wave_ok && ts === 4) return ['离场', 'stop', '逃顶四证齐全：' + tn.join('、'), bs, ts];
  if (ts >= 3) return ['减仓', 'warn', '逃顶三证：' + tn.join('、'), bs, ts];
  if (bs >= 3 && b.wave_ok) return ['关注', 'wait', '抄底三证，等第四证：' + bn.join('、'), bs, ts];
  return ['观望', 'idle', `抄底 ${bs}/4 · 逃顶 ${ts}/4`, bs, ts];
}
// bars: {d:[YYYY-MM-DD], o,h,l,c,v}; bar: 今天这根 {d,o,h,l,c,v}（d 与最后一根同日则替换，否则追加）
function evaluate(bars, cfg, bar) {
  const B = {o: bars.o.slice(), h: bars.h.slice(), l: bars.l.slice(), c: bars.c.slice(), v: bars.v.slice()};
  if (bar) {
    const n = bars.d.length, same = bars.d[n - 1] === bar.d, k = same ? n - 1 : n;
    B.o[k] = bar.o; B.h[k] = bar.h; B.l[k] = bar.l; B.c[k] = bar.c; B.v[k] = bar.v;
  }
  const e = new Engine(B, cfg), t = B.c.length - 1;
  const b = e.bottom(t), tp = e.top(t), r = verdict(b, tp); r.push(b, tp); return r;
}
root.BTQ4 = {evaluate, Engine, verdict};
if (typeof module !== 'undefined') module.exports = root.BTQ4;
})(typeof window !== 'undefined' ? window : globalThis);
