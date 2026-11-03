"""Alert delivery: prints always; POSTs JSON to a webhook when one is given."""
from __future__ import annotations
import json, urllib.request


FOOT = "仅供研究学习，不构成投资建议"
# 结论 → (飞书卡片头颜色, 字体颜色, 图标)；A 股习惯：红涨绿跌
STYLE = {"离场": ("red", "red", "🔴"), "减仓": ("orange", "orange", "🟠"), "入场": ("green", "green", "🟢"),
         "关注": ("blue", "blue", "🔵"), "观望": ("grey", "grey", "⚪"), "测试": ("wathet", "blue", "🧪")}
ORDER = ["离场", "减仓", "入场", "关注", "观望", "测试"]


def _num(x):
    if x in ("", None):
        return ""
    x = float(x)
    return f"{x:,.2f}" if abs(x) >= 100 else f"{x:.4g}"


def report(ov: dict, hits: list, site: str = "", test: bool = False) -> dict:
    """把收盘结论整理成卡片：title / template / sections(结论→行) / fields(概览) / link。"""
    c = ov.get("counts", {})
    top = next((v for v in ORDER if any(h["verdict"] == v for h in hits)), "观望")
    title = ("四证收盘结论 · 测试消息" if test else "四证收盘结论") + " · " + ov.get("generated", "")[:10]
    fields = [("生成时间", ov.get("generated", "")),
              ("今日结论", " · ".join(f"{k} {c.get(k, 0)}" for k in ["离场", "减仓", "入场", "关注", "观望"])),
              ("数据截至", " · ".join(f"{k} {v}" for k, v in ov.get("asof", {}).items())),
              ("模型", ov.get("model", ""))]
    sections = []
    for v in ORDER:
        rows = [h for h in hits if h["verdict"] == v]
        if rows:
            sections.append((v, rows))
    return dict(title=title, template=STYLE[top][0], fields=[f for f in fields if f[1]], sections=sections,
                link=site, test=test)


def _chg(p, mode):
    if p in ("", None):
        return ""
    p = float(p)
    t = f"{p:+.2f}%"
    if mode == "lark":
        return f"<font color='{'red' if p > 0 else 'green' if p < 0 else 'grey'}'>{t}</font>"
    if mode == "wecom":
        return f"<font color=\"{'warning' if p > 0 else 'info' if p < 0 else 'comment'}\">{t}</font>"
    return t


def _item_url(site, h):
    if not site or not h.get("symbol"):
        return ""
    from urllib.parse import quote
    return f"{site.rstrip('/')}/chart.html?symbol={quote(h['symbol'])}&name={quote(h.get('name', ''))}"


def to_markdown(r: dict, mode: str = "md") -> str:
    out = []
    for k, v in r["fields"]:
        out.append(f"**{k}**：{v}")
    for v, rows in r["sections"]:
        out.append("")
        out.append(f"{STYLE[v][2]} **{v}（{len(rows)}）**")
        for h in rows:
            u = _item_url(r["link"], h)
            name = f"[{h['name']}]({u})" if u else f"**{h['name']}**"
            price = _num(h.get("close"))
            out.append(f"{'•' if mode == 'lark' else '-'} {name}  {price} {_chg(h.get('chg_pct'), mode)}".rstrip())
            if h.get("reason"):
                out.append(f"  {h['reason']}" if mode != "lark" else f"    <font color='grey'>{h['reason']}</font>")
    if not r["sections"]:
        out += ["", "今天没有达到推送级别的结论。"]
    return "\n".join(out)


def payload(webhook: str, text: str, card: dict | None = None) -> dict:
    """飞书/Lark 发消息卡片，钉钉/企业微信发 markdown；没有 card 时发纯文本。其他地址发通用 JSON。"""
    w = webhook.lower()
    if "feishu" in w or "larksuite" in w:
        if not card:
            return {"msg_type": "text", "content": {"text": text}}
        els = [{"tag": "div", "text": {"tag": "lark_md", "content": to_markdown(card, "lark")}}]
        if card["link"]:
            els += [{"tag": "hr"}, {"tag": "action", "actions": [
                {"tag": "button", "text": {"tag": "plain_text", "content": "打开总览"}, "type": "primary", "url": card["link"]}]}]
        els.append({"tag": "note", "elements": [{"tag": "plain_text", "content": FOOT}]})
        return {"msg_type": "interactive", "card": {"config": {"wide_screen_mode": True},
                "header": {"template": card["template"], "title": {"tag": "plain_text", "content": card["title"]}},
                "elements": els}}
    if "dingtalk" in w:
        if not card:
            return {"msgtype": "text", "text": {"content": text}}
        md = f"### {card['title']}\n\n" + to_markdown(card).replace("\n", "\n\n") + (f"\n\n[打开总览]({card['link']})" if card["link"] else "") + f"\n\n> {FOOT}"
        return {"msgtype": "markdown", "markdown": {"title": card["title"], "text": md}}
    if "qyapi.weixin" in w:
        if not card:
            return {"msgtype": "text", "text": {"content": text}}
        md = f"**{card['title']}**\n" + to_markdown(card, "wecom") + (f"\n[打开总览]({card['link']})" if card["link"] else "") + f"\n> <font color=\"comment\">{FOOT}</font>"
        return {"msgtype": "markdown", "markdown": {"content": md[:4000]}}
    return {"text": text, "content": text, **({"card": card} if card else {})}


def post(webhook: str, text: str = "", card: dict | None = None) -> str:
    if card and not text:
        text = card["title"] + "\n" + to_markdown(card) + "\n" + FOOT
    req = urllib.request.Request(webhook, data=json.dumps(payload(webhook, text, card), ensure_ascii=False).encode(),
                                 headers={"Content-Type": "application/json"})
    res = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")
    try:  # bots answer HTTP 200 with an error code in the body (e.g. keyword / signature checks)
        j = json.loads(res)
        code = j.get("code", j.get("errcode", j.get("StatusCode", 0)))
        if code not in (0, None):
            raise RuntimeError(f"机器人返回错误 {code}: {j.get('msg') or j.get('errmsg') or res[:200]}")
    except ValueError:
        pass
    return res


def send(webhook, symbol, side, ev, close):
    name = "抄底" if side == "bottom" else "逃顶"
    text = (f"[{name}] {symbol} 证据 {ev.score}/4 {'信号成立' if ev.fired else '接近成立'}  收盘 {close:.4f}  "
            f"成本线 {ev.avwap:.4f}  止损 {ev.stop:.4f}")
    print("ALERT", text)
    if not webhook:
        return
    try:
        post(webhook, text)
    except Exception as ex:
        print("webhook failed:", ex)
