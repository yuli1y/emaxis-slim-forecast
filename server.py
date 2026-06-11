#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
JST = timezone(timedelta(hours=9), "JST")

FUND_SYMBOL = "0331418A.T"
FUND_CODE = "0331418A"
ACWI_SYMBOL = "ACWI"
FX_SYMBOL = "JPY=X"


def fetch_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 emaxis-slim-forecast/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.loads(response.read().decode("utf-8"))


def yahoo_chart(symbol: str, range_: str = "10d", interval: str = "1d") -> dict:
    encoded = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
        f"?range={range_}&interval={interval}&includePrePost=true"
    )
    payload = fetch_json(url)
    result = payload.get("chart", {}).get("result") or []
    if not result:
        error = payload.get("chart", {}).get("error") or {}
        raise RuntimeError(error.get("description") or f"No chart data for {symbol}")
    return result[0]


def compact_points(chart: dict) -> list[dict]:
    timestamps = chart.get("timestamp") or []
    quote = ((chart.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    previous = ((chart.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    values = previous or closes

    points = []
    for ts, close in zip(timestamps, values):
        if close is None or not math.isfinite(float(close)):
            continue
        points.append(
            {
                "date": datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d"),
                "value": float(close),
            }
        )
    return points


def latest_price(symbol: str) -> dict:
    chart = yahoo_chart(symbol, "5d", "1d")
    points = compact_points(chart)
    if len(points) < 2:
        raise RuntimeError(f"Not enough data for {symbol}")
    prev, latest = points[-2], points[-1]
    return {
        "symbol": symbol,
        "date": latest["date"],
        "value": latest["value"],
        "previousDate": prev["date"],
        "previousValue": prev["value"],
        "return": latest["value"] / prev["value"] - 1,
    }


def parse_number(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = value.replace(",", "").replace("%", "").strip()
    return float(cleaned)


def fetch_yahoo_japan_state(code: str) -> dict:
    url = f"https://finance.yahoo.co.jp/quote/{urllib.parse.quote(code)}"
    html = fetch_text(url)
    match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not match:
        raise RuntimeError("Yahoo Japanのページから基準価額データを抽出できませんでした")
    return json.loads(match.group(1))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 emaxis-slim-forecast/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        return response.read().decode("utf-8")


def latest_fund_price() -> dict:
    state = fetch_yahoo_japan_state(FUND_CODE)
    prices = state["mainFundPriceBoard"]["fundPrices"]
    page_info = state.get("pageInfo", {})
    nav = parse_number(prices["price"])
    change = parse_number(prices["changePrice"])
    change_pct = parse_number(prices["changePriceRate"]) / 100
    update_date = prices.get("updateDate", "")
    year = page_info.get("currentYear") or datetime.now(JST).strftime("%Y")
    date = f"{year}/{update_date}" if update_date else ""
    previous = nav - change
    return {
        "symbol": FUND_CODE,
        "date": date,
        "value": nav,
        "previousDate": "",
        "previousValue": previous,
        "return": change_pct,
        "change": change,
        "source": "Yahoo!ファイナンス",
    }


def safe_market_price(symbol: str, label: str) -> dict:
    try:
        data = latest_price(symbol)
        data["label"] = label
        data["error"] = ""
        return data
    except Exception as exc:
        return {
            "symbol": symbol,
            "label": label,
            "date": "",
            "value": 0,
            "previousDate": "",
            "previousValue": 0,
            "return": 0,
            "error": str(exc),
        }


def estimate(slot_hour: int, fund: dict, acwi: dict, fx: dict) -> dict:
    combined_return = acwi["return"] + fx["return"]
    predicted = fund["value"] * (1 + combined_return)
    diff = predicted - fund["value"]
    return {
        "slot": f"{slot_hour:02d}:00",
        "predictedNav": round(predicted),
        "change": round(diff),
        "changePct": combined_return,
        "drivers": {
            "acwiReturn": acwi["return"],
            "fxReturn": fx["return"],
        },
    }


def build_snapshot() -> dict:
    fund = latest_fund_price()
    acwi = safe_market_price(ACWI_SYMBOL, "ACWI ETF")
    fx = safe_market_price(FX_SYMBOL, "USD/JPY")
    now = datetime.now(JST)
    market_errors = [item["error"] for item in (acwi, fx) if item.get("error")]
    method = (
        "直近の基準価額に、ACWI ETF(米ドル建て)の日次変化率とドル円の日次変化率を"
        "単純加算して掛けた簡易推計です。信託報酬、配当、組入銘柄差、時差、休日差は未調整です。"
    )
    if market_errors:
        method += " 一部のマーケット材料を取得できなかったため、その材料の変化率は0%として表示しています。"

    return {
        "asOf": now.isoformat(timespec="seconds"),
        "fund": {
            "name": "eMAXIS Slim 全世界株式(オール・カントリー)",
            "symbol": FUND_CODE,
            "navDate": fund["date"],
            "nav": round(fund["value"]),
            "previousNavDate": fund["previousDate"],
            "previousNav": round(fund["previousValue"]),
            "actualChange": round(fund["change"]),
            "actualChangePct": fund["return"],
            "source": fund["source"],
        },
        "market": {
            "acwi": acwi,
            "usdJpy": fx,
        },
        "forecasts": [estimate(6, fund, acwi, fx), estimate(18, fund, acwi, fx)],
        "currentSlot": "06:00" if now.hour < 12 else "18:00",
        "method": method,
        "marketErrors": market_errors,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/snapshot":
            self.send_snapshot()
            return
        self.send_static(parsed.path)

    def do_HEAD(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        relative = "index.html" if parsed.path in ("", "/") else parsed.path.lstrip("/")
        target = (PUBLIC / relative).resolve()
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(target.stat().st_size))
        self.end_headers()

    def send_snapshot(self) -> None:
        try:
            payload = build_snapshot()
            status = 200
        except Exception as exc:
            payload = {"error": str(exc), "asOf": datetime.now(JST).isoformat(timespec="seconds")}
            status = 502
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (PUBLIC / relative).resolve()
        if PUBLIC not in target.parents and target != PUBLIC:
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}")


def main() -> None:
    port = int(os.environ.get("PORT", "8765"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Serving http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
