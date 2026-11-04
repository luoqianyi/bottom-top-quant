"""Build the static site (GitHub Pages): 首屏收盘结论 + 每个标的的详情数据。

    python scripts/build_site.py --out site                 # markets.yaml 里的全部标的
    python scripts/build_site.py --out site --webhook URL   # 顺便把 入场/离场/减仓 推送出去
"""
import argparse, datetime, json, re, shutil, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from btq.server import app, WEB  # noqa: E402

BARS_KEEP = 1500   # detail chart history kept in the static copy (analysis still uses the full history)
HIST_KEEP = 300    # 首屏“盘中预估”在浏览器里重算四证用的日线根数（与全量历史结果一致，已用 node 对过）
LIVE_RE = re.compile(r"^(sina:|csindex:000|hksina:(HSI|HSTECH|HSCEI)$)")   # 腾讯完整行情能给出开高低和时间的标的


def key(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--preset", default="relaxed")
    ap.add_argument("--webhook", default="")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--levels", default="入场,离场,减仓", help="推送哪些结论，逗号分隔")
    ap.add_argument("--site-url", default="", help="站点地址，推送卡片里的链接")
    ap.add_argument("--test-push", action="store_true", help="无论有没有信号，都发一条测试消息")
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(WEB, out / "static")
    for page in ("overview.html", "chart.html"):
        shutil.move(str(out / "static" / page), out / ("index.html" if page == "overview.html" else page))
    (out / ".nojekyll").write_text("")
    demo = out / "static" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    c = TestClient(app)

    def dump(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    ov = c.get("/api/overview", params=dict(preset=a.preset)).raise_for_status().json()
    dump(demo / "overview.json", ov)
    print(f"overview: {ov['total']} 个标的，{ov['errors']} 个失败，{ov['seconds']} 秒", ov["counts"])
    items = [it for g in ov["groups"] for it in g["items"] if not it.get("error")]

    HIST = {}

    def detail(it):
        s = it["symbol"]
        try:
            body = dict(symbol=s, preset=a.preset)
            b = c.get("/api/bars", params=dict(symbol=s)).raise_for_status().json()
            if LIVE_RE.match(s):
                cs = b["candles"][-HIST_KEEP:]
                vol = {x["time"]: x["value"] for x in b["volume"]}
                g = lambda x: float(f"{x:.7g}")
                HIST[s] = dict(d=[datetime.datetime.fromtimestamp(x["time"], datetime.timezone.utc).strftime("%Y-%m-%d") for x in cs],
                               o=[g(x["open"]) for x in cs], h=[g(x["high"]) for x in cs], l=[g(x["low"]) for x in cs],
                               c=[g(x["close"]) for x in cs], v=[g(vol.get(x["time"]) or 0) for x in cs])
            for k in ("candles", "volume", "dif", "dea", "hist", "vma5", "vma10"):
                b[k] = b[k][-BARS_KEEP:]
            b["ma"] = {n: v[-BARS_KEEP:] for n, v in b["ma"].items()}
            dump(demo / key(s) / "bars.json", b)
            for d in ("long", "short"):
                dump(demo / key(s) / f"analyze_{d}.json", c.post("/api/analyze", json=dict(body, direction=d)).raise_for_status().json())
            dump(demo / key(s) / "backtest.json", c.post("/api/backtest", json=body).raise_for_status().json())
            return s
        except Exception as ex:
            print("skip detail", s, ex)

    with ThreadPoolExecutor(a.workers) as ex:
        ok = [s for s in ex.map(detail, items) if s]
    presets = c.get("/api/presets").json()
    dump(demo / "presets.json", presets)
    cfg = next((p["params"] for p in presets if p["key"] == a.preset), None)
    dump(demo / "hist.json", dict(preset=a.preset, cfg=cfg, bars=HIST))
    scan = [dict(symbol=it["symbol"], date=it["date"], price=it["close"], change_pct=it["chg_pct"], bottom=it["bottom"],
                 bottom_fired=it["verdict"] == "入场", top=it["top"], top_fired=it["verdict"] == "离场",
                 composite=it["composite"], bias=it["bias"]) for it in items]
    dump(demo / "scan.json", scan)
    dump(demo / "index.json", dict(symbols=ok, names={it["symbol"]: it["name"] for it in items}))
    print("details:", len(ok), "site ->", out)

    levels = [x.strip() for x in a.levels.replace("，", ",").split(",") if x.strip()]
    hits = [it for it in items if it["verdict"] in levels]
    # 每个收盘点推一次：A股/港股/美股的数据日期 + 达到推送级别的信号；没有信号也发一条收盘日报
    closes = [f"{k}|{v}" for k, v in sorted(ov.get("asof", {}).items()) if k != "全球"]
    sig = closes + sorted(f"{it['symbol']}|{it['date']}|{it['verdict']}" for it in hits)
    dump(demo / "pushed.json", dict(sig=sig))
    send = True
    if a.site_url and not a.test_push:  # 备用定时、代码提交都会重跑，同一个收盘点只推一次
        try:
            import httpx
            prev = httpx.get(a.site_url.rstrip("/") + "/static/demo/pushed.json", timeout=15).json().get("sig")
            if prev == sig or (prev and not hits and all(x in prev for x in closes)):
                print("same close already pushed, skip")
                send = False
        except Exception as ex:
            print("dedupe check failed:", ex)
    if not a.webhook:
        print("no webhook configured, skip push")
    if a.webhook and (send or a.test_push):
        from btq.notify import post, report
        try:
            post(a.webhook, card=report(ov, hits, a.site_url, a.test_push))
            print("pushed", len(hits))
        except Exception as ex:
            print("push failed:", ex)


if __name__ == "__main__":
    main()
