"""Alert delivery: prints always; POSTs JSON to a webhook when one is given."""
from __future__ import annotations
import json, urllib.request


def payload(webhook: str, text: str) -> dict:
    """飞书/Lark、钉钉、企业微信机器人格式各不相同，按地址自动选；其他地址发通用 JSON。"""
    w = webhook.lower()
    if "feishu" in w or "larksuite" in w:
        return {"msg_type": "text", "content": {"text": text}}
    if "dingtalk" in w or "qyapi.weixin" in w:
        return {"msgtype": "text", "text": {"content": text}}
    return {"text": text, "content": text}


def post(webhook: str, text: str) -> str:
    req = urllib.request.Request(webhook, data=json.dumps(payload(webhook, text), ensure_ascii=False).encode(),
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
