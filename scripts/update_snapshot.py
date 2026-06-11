#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "data" / "snapshot.json"
JST = timezone(timedelta(hours=9), "JST")

FUND_CODE = "0331418A"
ACWI_SYMBOL = "ACWI"
FX_SYMBOL = "JPY=X"


def fetch_json(url: str, extra_headers: dict | None = None) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 emaxis-slim-forecast/1.0",
        "Accept": "application/json,text/plain,*/*",
    }
    if extra_headers:
        headers.update(extra_headers)
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 emaxis-slim-forecast/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def parse_number(value: str | int | float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return float(value.replace(",", "").replace("%", "").strip())


def yahoo_chart(symbol: str, range_: str = "5d", interval: str = "1d") -> dict:
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
    adjcloses = ((chart.get("indicators") or {}).get("adjclose") or [{}])[0].get("adjclose")
    values = adjcloses or closes

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


def latest_market_price(symbol: str, label: str) -> dict:
    try:
        points = compact_points(yahoo_chart(symbol))
        if len(points) < 2:
            raise RuntimeError(f"Not enough data for {symbol}")
        prev, latest = points[-2], points[-1]
        return {
            "symbol": symbol,
            "label": label,
            "date": latest["date"],
            "value": latest["value"],
            "previousDate": prev["date"],
            "previousValue": prev["value"],
            "return": latest["value"] / prev["value"] - 1,
            "error": "",
        }
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


def latest_fund_price() -> dict:
    url = f"https://finance.yahoo.co.jp/quote/{urllib.parse.quote(FUND_CODE)}"
    html = fetch_text(url)
    match = re.search(r"window\.__PRELOADED_STATE__\s*=\s*(\{.*?\})\s*</script>", html, re.S)
    if not match:
        raise RuntimeError("Yahoo Japanのページから基準価額データを抽出できませんでした")

    state = json.loads(match.group(1))
    prices = state["mainFundPriceBoard"]["fundPrices"]
    page_info = state.get("pageInfo", {})
    nav = parse_number(prices["price"])
    change = parse_number(prices["changePrice"])
    update_date = prices.get("updateDate", "")
    year = page_info.get("currentYear") or datetime.now(JST).strftime("%Y")

    return {
        "symbol": FUND_CODE,
        "date": f"{year}/{update_date}" if update_date else "",
        "value": nav,
        "previousValue": nav - change,
        "return": parse_number(prices["changePriceRate"]) / 100,
        "change": change,
        "source": "Yahoo!ファイナンス",
        "jwtToken": page_info.get("jwtToken", ""),
    }


def fund_history(fund: dict) -> list[dict]:
    existing = load_existing_snapshot() or {}
    existing_history = existing.get("fund", {}).get("history") or []
    try:
        now = datetime.now(JST)
        query = urllib.parse.urlencode(
            {
                "timeFrame": "daily",
                "fromDate": (now - timedelta(days=31)).strftime("%Y%m%d"),
                "toDate": now.strftime("%Y%m%d"),
                "size": "80",
            }
        )
        payload = fetch_json(
            f"https://finance.yahoo.co.jp/bff-pc/v1/main/fund/chart/history/{FUND_CODE}?{query}",
            {"jwt-token": fund["jwtToken"]},
        )
        points = [
            {"date": item["baseDate"], "value": float(item["closePrice"])}
            for item in payload.get("priceHistories", [])
            if item.get("baseDate") and item.get("closePrice") is not None
        ]
    except Exception:
        points = existing_history

    latest_point = {"date": fund["date"].replace("/", "-"), "value": fund["value"]}
    if not points:
        return [latest_point]

    if points[-1].get("date") != latest_point["date"]:
        points = [*points, latest_point]
    else:
        points[-1] = latest_point

    return points[-31:]


def estimate(slot_hour: int, fund: dict, acwi: dict, fx: dict) -> dict:
    combined_return = acwi["return"] + fx["return"]
    predicted = fund["value"] * (1 + combined_return)
    return {
        "slot": f"{slot_hour:02d}:00",
        "status": "ready",
        "predictedNav": round(predicted),
        "change": round(predicted - fund["value"]),
        "changePct": combined_return,
        "drivers": {
            "acwiReturn": acwi["return"],
            "fxReturn": fx["return"],
        },
    }


def pending_forecast(slot: str, message: str) -> dict:
    return {
        "slot": slot,
        "status": "pending",
        "message": message,
        "predictedNav": None,
        "change": None,
        "changePct": None,
        "drivers": {
            "acwiReturn": None,
            "fxReturn": None,
        },
    }


def active_slot(now: datetime) -> str:
    if 10 <= now.hour < 18:
        return "10:00"
    return "18:00"


def load_existing_snapshot() -> dict | None:
    if not DATA_PATH.exists():
        return None
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_forecasts(now: datetime, fund: dict, acwi: dict, fx: dict) -> list[dict]:
    current_slot = active_slot(now)
    forecasts = {
        "10:00": pending_forecast("10:00", "10:00更新後に表示します。"),
        "18:00": pending_forecast("18:00", "18:00更新後に表示します。"),
    }

    existing = load_existing_snapshot()
    if existing and existing.get("fund", {}).get("navDate") == fund["date"]:
        for forecast in existing.get("forecasts", []):
            if forecast.get("slot") in forecasts and forecast.get("status") == "ready":
                forecasts[forecast["slot"]] = forecast

    if current_slot == "10:00":
        forecasts["10:00"] = estimate(10, fund, acwi, fx)
        forecasts["18:00"] = pending_forecast("18:00", "18:00更新後に表示します。")
    else:
        forecasts["18:00"] = estimate(18, fund, acwi, fx)

    return [forecasts["10:00"], forecasts["18:00"]]


def build_snapshot() -> dict:
    fund = latest_fund_price()
    history = fund_history(fund)
    acwi = latest_market_price(ACWI_SYMBOL, "ACWI ETF")
    fx = latest_market_price(FX_SYMBOL, "USD/JPY")
    now = datetime.now(JST)
    slot = active_slot(now)
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
            "previousNav": round(fund["previousValue"]),
            "actualChange": round(fund["change"]),
            "actualChangePct": fund["return"],
            "source": fund["source"],
            "history": history,
        },
        "market": {
            "acwi": acwi,
            "usdJpy": fx,
        },
        "forecasts": build_forecasts(now, fund, acwi, fx),
        "currentSlot": slot,
        "method": method,
        "marketErrors": market_errors,
    }


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATA_PATH.write_text(
        json.dumps(build_snapshot(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
