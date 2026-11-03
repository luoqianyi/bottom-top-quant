"""Build the static site (GitHub Pages): 首屏收盘结论 + 每个标的的详情数据。

    python scripts/build_site.py --out site                 # markets.yaml 里的全部标的
    python scripts/build_site.py --out site --webhook URL   # 顺便把 入场/离场/减仓 推送出去
"""
import argparse, json, re, shutil, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from btq.server import app, WEB  # noqa: E402

BARS_KEEP = 1500   # detail chart history kept in the static copy (analysis still uses the full history)


def key(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--preset", default="relaxed")
    ap.add_argument("--webhook", default="")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--levels", default="入场,离场,减仓", help="推送哪些结论，逗号分隔")
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

    def detail(it):
        s = it["symbol"]
        try:
            body = dict(symbol=s, preset=a.preset)
            b = c.get("/api/bars", params=dict(symbol=s)).raise_for_status().json()
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
    dump(demo / "presets.json", c.get("/api/presets").json())
    scan = [dict(symbol=it["symbol"], date=it["date"], price=it["close"], change_pct=it["chg_pct"], bottom=it["bottom"],
                 bottom_fired=it["verdict"] == "入场", top=it["top"], top_fired=it["verdict"] == "离场",
                 composite=it["composite"], bias=it["bias"]) for it in items]
    dump(demo / "scan.json", scan)
    dump(demo / "index.json", dict(symbols=ok, names={it["symbol"]: it["name"] for it in items}))
    print("details:", len(ok), "site ->", out)

    levels = [x.strip() for x in a.levels.replace("，", ",").split(",") if x.strip()]
    hits = [it for it in items if it["verdict"] in levels]
    if not a.webhook:
        print("no webhook configured, skip push")
    elif a.test_push and not hits:
        hits = [dict(verdict="测试", name="推送通道", close="", chg_pct=0.0, reason="配置成功，收盘有信号时会推送到这里")]
    if a.webhook and hits:
        text = ("【测试】" if a.test_push else "") + "四证收盘结论 " + ov["generated"] + "\n" + "\n".join(f"[{it['verdict']}] {it['name']} {it['close']} ({it['chg_pct']:+.2f}%) {it['reason']}" for it in hits) + "\n仅供研究学习，不构成投资建议"
        from btq.notify import post
        try:
            post(a.webhook, text)
            print("pushed", len(hits))
        except Exception as ex:
            print("push failed:", ex)


if __name__ == "__main__":
    main()
