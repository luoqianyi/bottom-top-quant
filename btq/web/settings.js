/* ⚙ 设置：大模型（浏览器直连）+ 收盘推送（通过 GitHub API 写仓库变量、触发 Actions）。所有凭据只存在本浏览器 localStorage。 */
(() => {
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const PROVIDERS = [
  ['openrouter', 'OpenRouter', 'https://openrouter.ai/api/v1', 'deepseek/deepseek-chat'],
  ['deepseek', 'DeepSeek', 'https://api.deepseek.com/v1', 'deepseek-chat'],
  ['siliconflow', '硅基流动', 'https://api.siliconflow.cn/v1', 'deepseek-ai/DeepSeek-V3'],
  ['dashscope', '通义千问（百炼）', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus'],
  ['moonshot', 'Kimi（Moonshot）', 'https://api.moonshot.cn/v1', 'moonshot-v1-8k'],
  ['zhipu', '智谱 GLM', 'https://open.bigmodel.cn/api/paas/v4', 'glm-4-flash'],
  ['groq', 'Groq', 'https://api.groq.com/openai/v1', 'llama-3.3-70b-versatile'],
  ['openai', 'OpenAI', 'https://api.openai.com/v1', 'gpt-4o-mini'],
  ['ollama', 'Ollama（本机）', 'http://localhost:11434/v1', 'qwen2.5:14b'],
  ['custom', '自定义', '', ''],
];
const LEVELS = ['入场', '离场', '减仓', '关注'];
const ld = k => JSON.parse(localStorage[k] || '{}');
function guessRepo() {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  return m ? `${m[1]}/${location.pathname.split('/').filter(Boolean)[0] || ''}` : 'luoqianyi/bottom-top-quant';
}

const css = `
.st-mask{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:50;display:flex;justify-content:flex-end}
.st-mask[hidden]{display:none!important}
.st-sheet{width:min(460px,100%);height:100%;overflow:auto;background:#14110e;border-left:1px solid rgba(255,255,255,.08);padding:16px 16px calc(24px + env(safe-area-inset-bottom));color:#ece7df;font:14px/1.45 -apple-system,"PingFang SC","Noto Sans SC",sans-serif}
.st-sheet h3{margin:0;font-size:18px}.st-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.st-sec{border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:12px;margin:12px 0;background:#1a1612}
.st-sec h4{margin:0 0 2px;font-size:15px;display:flex;justify-content:space-between;align-items:center}
.st-sheet label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:#8e867b;margin:9px 0}
.st-sheet input:not([type=checkbox]),.st-sheet select{width:100%;box-sizing:border-box;background:#0f0d0b;border:1px solid rgba(255,255,255,.1);border-radius:8px;color:#ece7df;padding:8px 10px;font:13px ui-monospace,Menlo,monospace}
.st-sheet .ck{flex-direction:row;align-items:center;gap:6px;color:#cfc8bd;font-size:13px;margin:4px 12px 4px 0;display:inline-flex}
.st-btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:8px}
.st-btns button,.st-x{border:1px solid rgba(255,255,255,.14);background:#221d17;color:#ece7df;border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer}
.st-btns .pri{background:#22d3ee;color:#04161a;border-color:#22d3ee;font-weight:700}
.st-note{font-size:11.5px;color:#8e867b;line-height:1.6;margin-top:8px}.st-note a{color:#67e8f9}
.st-msg{font-size:12.5px;margin-top:8px;color:#cfc8bd;white-space:pre-wrap}.st-msg.ok{color:#67e8f9}.st-msg.err{color:#fca5a5}
.st-pill{font-size:11px;border-radius:999px;padding:2px 8px;background:rgba(255,255,255,.07);color:#a8a097;font-weight:600}.st-pill.on{background:rgba(34,211,238,.18);color:#67e8f9}
.st-gear{border:1px solid rgba(255,255,255,.12);background:#1a1713;color:#ece7df;border-radius:999px;padding:4px 10px;font:inherit;font-size:13px;cursor:pointer}
`;
function mount() {
  if ($('#stMask')) return;
  const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
  const L = Object.assign({provider: 'openrouter', base: '', model: '', key: '', auto: true, stream: true, temp: 0.3, sys: ''}, ld('btqLLM'));
  const G = Object.assign({repo: guessRepo(), token: '', webhook: '', levels: ['入场', '离场', '减仓']}, ld('btqPush'));
  const d = document.createElement('div'); d.className = 'st-mask'; d.id = 'stMask'; d.hidden = true;
  d.innerHTML = `<div class="st-sheet">
    <div class="st-top"><h3>⚙ 设置</h3><button class="st-x" id="stClose">关闭</button></div>
    <div class="st-sec">
      <h4>✦ 大模型 <span class="st-pill" id="stLlmState"></span></h4>
      <div class="st-note" style="margin:0">用于详情页的「AI 深度解读」和「对话」。浏览器直接调用你填的接口（兼容 OpenAI）。</div>
      <label>服务商<select id="stProv">${PROVIDERS.map(p => `<option value="${p[0]}">${p[1]}</option>`).join('')}</select></label>
      <label>接口地址 Base URL<input id="stBase" spellcheck="false" autocomplete="off"></label>
      <label>模型<input id="stModel" spellcheck="false" autocomplete="off"></label>
      <label>API Key<input id="stKey" type="password" spellcheck="false" autocomplete="off" placeholder="sk-..."></label>
      <span class="ck"><input type="checkbox" id="stAuto"> 分析后自动生成 AI 解读</span><span class="ck"><input type="checkbox" id="stStream"> 流式输出</span>
      <div class="st-btns"><button class="pri" id="stLlmSave">保存</button><button id="stLlmTest">测试连接</button><button id="stLlmClear">清除</button></div>
      <div class="st-msg" id="stLlmMsg"></div>
    </div>
    <div class="st-sec">
      <h4>🔔 收盘推送 <span class="st-pill" id="stPushState">检查中</span></h4>
      <div class="st-note" style="margin:0">每个交易日收盘后由 GitHub Actions 运行（触发时间见下方「收盘定时」），把选中结论的标的推到飞书 / 钉钉 / 企业微信机器人。</div>
      <label>机器人 Webhook 地址<input id="stHook" spellcheck="false" autocomplete="off" placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/..."></label>
      <div>${LEVELS.map(l => `<span class="ck"><input type="checkbox" data-lv="${l}"> ${l}</span>`).join('')}</div>
      <label>仓库<input id="stRepo" spellcheck="false" autocomplete="off"></label>
      <label>GitHub 令牌（fine-grained，只给这个仓库 Actions + Variables 读写）<input id="stTok" type="password" spellcheck="false" autocomplete="off" placeholder="github_pat_..."></label>
      <div class="st-btns"><button class="pri" id="stPushSave">保存到仓库</button><button id="stPushTest">发送测试消息</button><button id="stRun">立即运行一次</button></div>
      <div class="st-msg" id="stPushMsg"></div>
      <div class="st-note">「保存到仓库」会把 Webhook 和推送级别写成仓库的 Actions 变量 ALERT_WEBHOOK / ALERT_LEVELS（不会公开显示，日志里也不打印）。令牌只存在本浏览器，用来调用 GitHub API；不想给令牌，也可以手动去 <a id="stVarLink" target="_blank" rel="noopener">仓库 → Settings → Secrets and variables → Actions</a> 新建 secret ALERT_WEBHOOK。
      <br><a id="stTokLink" target="_blank" rel="noopener" href="https://github.com/settings/personal-access-tokens/new">创建令牌</a> · <a id="stRunsLink" target="_blank" rel="noopener">运行记录</a></div>
    </div>
    <div class="st-sec">
      <h4>⏰ 收盘定时 <span class="st-pill" id="stCronState">未读取</span></h4>
      <div class="st-note" style="margin:0">GitHub 自带定时经常被丢弃，改由 cron-job.org 按时调用 GitHub 接口触发构建。这里可以直接改触发时间、开关任务（北京时间）。</div>
      <label>cron-job.org API Key（控制台 Settings → API）<input id="stCronKey" type="password" spellcheck="false" autocomplete="off"></label>
      <div id="stCronJobs"></div>
      <div class="st-btns"><button class="pri" id="stCronLoad">读取定时</button><button id="stCronNew">一键创建两个定时</button></div>
      <div class="st-msg" id="stCronMsg"></div>
      <div class="st-note">「一键创建」会用上面填的 GitHub 令牌建两个任务：周一到周五 16:20（A股、港股收盘后），周二到周六 05:20（美股收盘后）。<a target="_blank" rel="noopener" href="https://console.cron-job.org/jobs">打开 cron-job.org 控制台</a></div>
    </div>
    <div class="st-note">所有设置只存在这台设备的浏览器里，换设备或清缓存需要重新填。内容仅作研究学习，不构成投资建议。</div>
  </div>`;
  document.body.appendChild(d);
  d.onclick = e => { if (e.target === d) close(); }; $('#stClose').onclick = close;

  // ---------- LLM
  const fillL = () => { $('#stProv').value = L.provider; $('#stBase').value = L.base; $('#stModel').value = L.model; $('#stKey').value = L.key; $('#stAuto').checked = L.auto; $('#stStream').checked = L.stream;
    const ok = L.base && L.model && (L.key || /localhost|127\.0\.0\.1/.test(L.base)); $('#stLlmState').textContent = ok ? '已启用 · ' + L.model : '未配置'; $('#stLlmState').className = 'st-pill' + (ok ? ' on' : ''); };
  $('#stProv').onchange = () => { const p = PROVIDERS.find(x => x[0] === $('#stProv').value); if (p[2]) $('#stBase').value = p[2]; if (p[3]) $('#stModel').value = p[3]; };
  const readL = () => Object.assign(L, {provider: $('#stProv').value, base: $('#stBase').value.trim(), model: $('#stModel').value.trim(), key: $('#stKey').value.trim(), auto: $('#stAuto').checked, stream: $('#stStream').checked});
  $('#stLlmSave').onclick = () => { readL(); localStorage.btqLLM = JSON.stringify(L); fillL(); msg('#stLlmMsg', '已保存，只存在本浏览器。打开详情页即可使用。', 'ok'); };
  $('#stLlmClear').onclick = () => { localStorage.removeItem('btqLLM'); Object.assign(L, {base: '', model: '', key: ''}); fillL(); msg('#stLlmMsg', '已清除。'); };
  $('#stLlmTest').onclick = async () => {
    readL(); msg('#stLlmMsg', '测试中…');
    try {
      const h = {'Content-Type': 'application/json'}; if (L.key) h.Authorization = 'Bearer ' + L.key;
      const r = await fetch(L.base.replace(/\/+$/, '') + '/chat/completions', {method: 'POST', headers: h, body: JSON.stringify({model: L.model, messages: [{role: 'user', content: '只回复两个字：在线'}]})});
      const t = await r.text(); if (!r.ok) throw new Error(`HTTP ${r.status}：${t.slice(0, 160)}`);
      msg('#stLlmMsg', '连接成功：' + (JSON.parse(t).choices?.[0]?.message?.content || '').slice(0, 30) + '。记得点「保存」。', 'ok');
    } catch (e) { msg('#stLlmMsg', '失败：' + (e.message === 'Failed to fetch' ? '连不上（网络或该服务商不允许浏览器跨域直连），换一家试试' : e.message), 'err'); }
  };
  fillL(); if (!L.base) $('#stProv').onchange();

  // ---------- push (GitHub API)
  const fillG = () => { $('#stHook').value = G.webhook; $('#stRepo').value = G.repo; $('#stTok').value = G.token;
    document.querySelectorAll('[data-lv]').forEach(c => c.checked = G.levels.includes(c.dataset.lv));
    $('#stVarLink').href = `https://github.com/${G.repo}/settings/secrets/actions`; $('#stRunsLink').href = `https://github.com/${G.repo}/actions/workflows/market-close.yml`; };
  const readG = () => Object.assign(G, {webhook: $('#stHook').value.trim(), repo: $('#stRepo').value.trim(), token: $('#stTok').value.trim(), levels: [...document.querySelectorAll('[data-lv]:checked')].map(c => c.dataset.lv)});
  const saveLocal = () => localStorage.btqPush = JSON.stringify(G);
  async function gh(path, method = 'GET', body) {
    if (!G.token) throw new Error('先填 GitHub 令牌');
    const r = await fetch(`https://api.github.com/repos/${G.repo}${path}`, {method, headers: {Authorization: 'Bearer ' + G.token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', ...(body ? {'Content-Type': 'application/json'} : {})}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 404 && method === 'PATCH') return r;
    if (!r.ok) { const t = await r.text(); let m = t; try { m = JSON.parse(t).message; } catch (e) {} throw new Error(`GitHub ${r.status}：${m}` + (r.status === 403 || r.status === 401 ? '（令牌权限不够：需要这个仓库的 Actions 和 Variables 读写）' : '')); }
    return r;
  }
  async function setVar(name, value) {
    const r = await gh(`/actions/variables/${name}`, 'PATCH', {name, value});
    if (r.status === 404) await gh('/actions/variables', 'POST', {name, value});
  }
  async function status() {
    readG(); fillG();
    if (!G.token) { $('#stPushState').textContent = G.webhook ? '本地已填，未写入仓库' : '未配置'; $('#stPushState').className = 'st-pill'; return; }
    try { const r = await gh('/actions/variables/ALERT_WEBHOOK'); const v = (await r.json()).value || '';
      $('#stPushState').textContent = '已配置 · ' + v.replace(/^(https?:\/\/[^/]+).*?(.{4})$/, '$1/…$2'); $('#stPushState').className = 'st-pill on';
    } catch (e) { $('#stPushState').textContent = /404/.test(e.message) ? '仓库未配置' : '无法读取'; $('#stPushState').className = 'st-pill'; }
  }
  async function dispatch(test) {
    await gh('/actions/workflows/market-close.yml/dispatches', 'POST', {ref: 'main', inputs: {test_push: test ? 'true' : 'false'}});
  }
  $('#stPushSave').onclick = async () => {
    readG(); saveLocal();
    if (!/^https:\/\//.test(G.webhook)) return msg('#stPushMsg', 'Webhook 地址要以 https:// 开头', 'err');
    if (!G.levels.length) return msg('#stPushMsg', '至少选一个推送级别', 'err');
    msg('#stPushMsg', '写入仓库变量…');
    try { await setVar('ALERT_WEBHOOK', G.webhook); await setVar('ALERT_LEVELS', G.levels.join(',')); msg('#stPushMsg', '已保存到仓库。下次收盘会自动推送：' + G.levels.join('、') + '。可以先点「发送测试消息」。', 'ok'); status(); }
    catch (e) { msg('#stPushMsg', '失败：' + e.message, 'err'); }
  };
  $('#stPushTest').onclick = async () => { readG(); saveLocal(); msg('#stPushMsg', '触发中…');
    try { await dispatch(true); msg('#stPushMsg', '已触发。GitHub Actions 大约 2 分钟后发出测试消息，同时更新页面。', 'ok'); } catch (e) { msg('#stPushMsg', '失败：' + e.message, 'err'); } };
  $('#stRun').onclick = async () => { readG(); saveLocal(); msg('#stPushMsg', '触发中…');
    try { await dispatch(false); msg('#stPushMsg', '已触发。大约 2 分钟后页面更新，有符合级别的标的就会推送。', 'ok'); } catch (e) { msg('#stPushMsg', '失败：' + e.message, 'err'); } };
  fillG();
  d._status = status;

  // ---------- 收盘定时（cron-job.org REST API，允许浏览器跨域）
  const C = Object.assign({key: ''}, ld('btqCron'));
  const WD = ['日', '一', '二', '三', '四', '五', '六'];
  $('#stCronKey').value = C.key;
  async function cj(path, method = 'GET', body) {
    C.key = $('#stCronKey').value.trim(); localStorage.btqCron = JSON.stringify(C);
    if (!C.key) throw new Error('先填 cron-job.org API Key');
    const r = await fetch('https://api.cron-job.org' + path, {method, headers: {Authorization: 'Bearer ' + C.key, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
    const t = await r.text(); if (!r.ok) throw new Error(`cron-job.org ${r.status}` + (r.status === 401 ? '（API Key 不对）' : r.status === 429 ? '（请求太频繁，稍后再试）' : '') + (t ? '：' + t.slice(0, 120) : ''));
    return t ? JSON.parse(t) : {};
  }
  const two = n => String(n).padStart(2, '0');
  function row(j) {
    const s = j.schedule || {}, h = (s.hours || [0])[0], m = (s.minutes || [0])[0], wd = s.wdays || [-1];
    return `<div class="st-sec" data-job="${j.jobId}" style="margin:8px 0;padding:10px">
      <div style="display:flex;justify-content:space-between;align-items:center"><b style="font-size:13px">${esc(j.title || j.url)}</b><span class="ck" style="margin:0"><input type="checkbox" data-en ${j.enabled ? 'checked' : ''}> 启用</span></div>
      <label>时间（北京时间）<input type="time" data-t value="${two(h < 0 ? 0 : h)}:${two(m < 0 ? 0 : m)}"></label>
      <div>${WD.map((w, i) => `<span class="ck" style="margin-right:6px"><input type="checkbox" data-wd="${i}" ${wd.includes(-1) || wd.includes(i) ? 'checked' : ''}>${w}</span>`).join('')}</div>
      <div class="st-btns"><button data-save>保存</button><span class="st-msg" data-m style="margin:0;align-self:center"></span></div>
      ${j.lastStatus !== undefined && j.lastExecution ? `<div class="st-note">上次执行 ${new Date(j.lastExecution * 1000).toLocaleString('zh-CN', {timeZone: 'Asia/Shanghai', hour12: false})} · ${j.lastStatus === 1 ? '成功' : '状态码 ' + j.lastStatus}</div>` : ''}
    </div>`;
  }
  async function loadJobs() {
    msg('#stCronMsg', '读取中…');
    try {
      const jobs = ((await cj('/jobs')).jobs || []).filter(j => /actions\/workflows/.test(j.url || '') || /^btq/.test(j.title || ''));
      $('#stCronJobs').innerHTML = jobs.map(row).join('');
      $('#stCronState').textContent = jobs.length ? `${jobs.filter(j => j.enabled).length}/${jobs.length} 个启用` : '没有定时'; $('#stCronState').className = 'st-pill' + (jobs.some(j => j.enabled) ? ' on' : '');
      msg('#stCronMsg', jobs.length ? '' : '还没有触发构建的定时，可以点「一键创建两个定时」。', jobs.length ? '' : 'err');
      document.querySelectorAll('[data-job]').forEach(el => el.querySelector('[data-save]').onclick = async () => {
        const [h, m] = el.querySelector('[data-t]').value.split(':').map(Number), wd = [...el.querySelectorAll('[data-wd]:checked')].map(c => +c.dataset.wd);
        const out = el.querySelector('[data-m]');
        if (!wd.length) { out.textContent = '至少选一天'; out.className = 'st-msg err'; return; }
        out.textContent = '保存中…'; out.className = 'st-msg';
        try { await cj('/jobs/' + el.dataset.job, 'PATCH', {job: {enabled: el.querySelector('[data-en]').checked, schedule: {timezone: 'Asia/Shanghai', hours: [h], minutes: [m], wdays: wd.length === 7 ? [-1] : wd, mdays: [-1], months: [-1]}}});
          out.textContent = '已保存'; out.className = 'st-msg ok'; } catch (e) { out.textContent = e.message; out.className = 'st-msg err'; }
      });
    } catch (e) { msg('#stCronMsg', '失败：' + (e.message === 'Failed to fetch' ? '连不上 cron-job.org' : e.message), 'err'); }
  }
  $('#stCronLoad').onclick = loadJobs;
  $('#stCronNew').onclick = async () => {
    readG(); saveLocal();
    if (!G.token) return msg('#stCronMsg', '先在上面「收盘推送」里填 GitHub 令牌', 'err');
    const mk = (title, h, m, wd) => ({job: {title, enabled: true, saveResponses: false, url: `https://api.github.com/repos/${G.repo}/actions/workflows/market-close.yml/dispatches`,
      requestMethod: 1, extendedData: {headers: {Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', Authorization: 'Bearer ' + G.token}, body: '{"ref":"main"}'},
      schedule: {timezone: 'Asia/Shanghai', hours: [h], minutes: [m], wdays: wd, mdays: [-1], months: [-1]}}});
    msg('#stCronMsg', '创建中…');
    try { await cj('/jobs', 'PUT', mk('btq 港A股收盘构建', 16, 20, [1, 2, 3, 4, 5])); await cj('/jobs', 'PUT', mk('btq 美股收盘构建', 5, 20, [2, 3, 4, 5, 6])); await loadJobs(); msg('#stCronMsg', '已创建两个定时。', 'ok'); }
    catch (e) { msg('#stCronMsg', '失败：' + e.message, 'err'); }
  };
  d._cron = () => { if (C.key) loadJobs(); };
}
function msg(sel, t, cls) { const el = $(sel); el.textContent = t; el.className = 'st-msg ' + (cls || ''); }
function open() { mount(); $('#stMask').hidden = false; $('#stMask')._status(); $('#stMask')._cron(); }
function close() { $('#stMask').hidden = true; if (window.btqReloadLLM) window.btqReloadLLM(); }
window.btqSettings = open;
document.addEventListener('keydown', e => { if (e.key === 'Escape' && $('#stMask') && !$('#stMask').hidden) close(); });
document.addEventListener('click', e => { if (e.target.closest('[data-settings]')) { e.preventDefault(); open(); } });
if (location.hash === '#settings') addEventListener('load', open);
})();
