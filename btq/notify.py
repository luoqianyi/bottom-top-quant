"""Alert delivery: prints always; POSTs JSON to a webhook when one is given."""
from __future__ import annotations
import json, urllib.request


def send(webhook, symbol, side, ev, close):
    name = "抄底" if side == "bottom" else "逃顶"
    text = (f"[{name}] {symbol} 证据 {ev.score}/4 {'信号成立' if ev.fired else '接近成立'}  收盘 {close:.4f}  "
            f"成本线 {ev.avwap:.4f}  止损 {ev.stop:.4f}")
    print("ALERT", text)
    if not webhook:
        return
    body = json.dumps({"msgtype": "text", "text": {"content": text}, "content": text}).encode()
    req = urllib.request.Request(webhook, data=body, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as ex:
        print("webhook failed:", ex)
