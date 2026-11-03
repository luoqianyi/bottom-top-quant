"""Build a static copy of the web terminal (for GitHub Pages): front-end + pre-computed demo data.

    python scripts/build_site.py --out site --symbols BTC-USD 300750.SZ AAPL
"""
import argparse, json, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402
from btq.server import app, WEB  # noqa: E402


def key(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site")
    ap.add_argument("--preset", default="strict")
    ap.add_argument("--symbols", nargs="+", default=["300750.SZ", "BTC-USD", "NVDA", "AAPL", "600519.SS", "0700.HK"])
    a = ap.parse_args()
    out = Path(a.out)
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(WEB, out / "static")
    shutil.move(str(out / "static" / "index.html"), out / "index.html")
    demo = out / "static" / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    c = TestClient(app)

    def dump(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    ok = []
    for s in a.symbols:
        try:
            body = dict(symbol=s, preset=a.preset)
            dump(demo / key(s) / "bars.json", c.get("/api/bars", params=dict(symbol=s)).raise_for_status().json())
            for d in ("long", "short"):
                dump(demo / key(s) / f"analyze_{d}.json", c.post("/api/analyze", json=dict(body, direction=d)).raise_for_status().json())
            dump(demo / key(s) / "backtest.json", c.post("/api/backtest", json=body).raise_for_status().json())
            ok.append(s)
            print("ok", s)
        except Exception as ex:
            print("skip", s, ex)
    dump(demo / "presets.json", c.get("/api/presets").json())
    dump(demo / "scan.json", c.post("/api/scan", json=dict(symbols=ok, preset="relaxed")).json())
    dump(demo / "index.json", dict(symbols=ok))
    print("site ->", out)


if __name__ == "__main__":
    main()
