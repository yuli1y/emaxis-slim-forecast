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
ESTIMATED_ERROR_PCT = 0.01


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


def fetch_fund_data_from_nikkei() -> dict:
    url = f"https://www.nikkei.com/nkd/fund/?fcode={FUND_CODE}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        html = response.read().decode("utf-8")
        
    date_match = re.search(r"<dt class=\"m-stockPriceElm_title\">基準価格\((.*?)\)：</dt>", html)
    if not date_match:
        raise RuntimeError("日経新聞のページから基準日を取得できませんでした")
    date_text = date_match.group(1)
    month, day = map(int, date_text.split("/"))
    now = datetime.now(JST)
    year = now.year
    if now.month == 1 and month == 12:
        year -= 1
    date_formatted = f"{year}/{month:02d}/{day:02d}"
    
    price_match = re.search(r"<dd class=\"m-stockPriceElm_value now\">([\d,]+)", html)
    if not price_match:
        raise RuntimeError("日経新聞のページから基準価格を取得できませんでした")
    nav = float(price_match.group(1).replace(",", ""))
    
    change_match = re.search(r"<dt class=\"m-stockPriceElm_title\">前日比：</dt>\s*<dd class=\"[^\"]*\">([+\-\d,]+)", html)
    if not change_match:
        raise RuntimeError("日経新聞のページから前日比を取得できませんでした")
    change = float(change_match.group(1).replace(",", ""))
    
    change_idx = change_match.end()
    pct_match = re.search(r"\(([+\-\d\.,]+)%\)", html[change_idx:change_idx+100])
    if not pct_match:
        raise RuntimeError("日経新聞のページから前日比率を取得できませんでした")
    change_rate = float(pct_match.group(1)) / 100
    
    return {
        "symbol": FUND_CODE,
        "date": date_formatted,
        "value": nav,
        "previousValue": nav - change,
        "return": change_rate,
        "change": change,
        "source": "日本経済新聞",
        "jwtToken": "",
    }


def latest_fund_price(fund_data: dict) -> dict:
    return fund_data


def fund_history(fund: dict) -> list[dict]:
    existing = load_existing_snapshot() or {}
    existing_history = existing.get("fund", {}).get("history") or []
    
    latest_point = {"date": fund["date"].replace("/", "-"), "value": fund["value"]}
    if not existing_history:
        return [latest_point]
        
    points = existing_history
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
    if 6 <= now.hour < 18:
        return "06:00"
    if 18 <= now.hour < 23:
        return "18:00"
    return "next"


def next_business_date(date_text: str) -> str:
    base = datetime.strptime(date_text, "%Y/%m/%d").date()
    target = base + timedelta(days=1)
    while target.weekday() >= 5:
        target += timedelta(days=1)
    return target.strftime("%Y/%m/%d")


def load_existing_snapshot() -> dict | None:
    if not DATA_PATH.exists():
        return None
    try:
        return json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_forecasts(now: datetime, fund: dict, acwi: dict, fx: dict) -> list[dict]:
    current_slot = active_slot(now)
    forecast_date = now.strftime("%Y/%m/%d")
    forecasts = {
        "06:00": pending_forecast("06:00", f"{forecast_date} 06:00更新後に表示します。"),
        "18:00": pending_forecast("18:00", f"{forecast_date} 18:00更新後に表示します。"),
    }

    existing = load_existing_snapshot()
    if current_slot != "next" and existing and existing.get("fund", {}).get("navDate") == fund["date"]:
        for forecast in existing.get("forecasts", []):
            if forecast.get("slot") in forecasts and forecast.get("status") == "ready":
                forecasts[forecast["slot"]] = forecast

    if current_slot == "06:00":
        forecasts["06:00"] = estimate(6, fund, acwi, fx)
        forecasts["18:00"] = pending_forecast("18:00", f"{forecast_date} 18:00更新後に表示します。")
    elif current_slot == "18:00":
        forecasts["18:00"] = estimate(18, fund, acwi, fx)

    return [forecasts["06:00"], forecasts["18:00"]]


def build_snapshot() -> dict:
    fund_data = fetch_fund_data_from_nikkei()
    fund = latest_fund_price(fund_data)
    history = fund_history(fund)
    acwi = latest_market_price(ACWI_SYMBOL, "ACWI ETF")
    fx = latest_market_price(FX_SYMBOL, "USD/JPY")
    now = datetime.now(JST)
    slot = active_slot(now)
    market_errors = [item["error"] for item in (acwi, fx) if item.get("error")]

    method = (
        "直近の基準価額に、ACWI ETF(米ドル建て)の日次変化率とドル円の日次変化率を"
        "単純加算して掛けた予想基準価額です。実際の採用為替、評価タイミング、組入差、ETF固有要因は未調整です。"
        f" 目安として推計値の±{ESTIMATED_ERROR_PCT:.0%}程度ずれる可能性があります。"
    )
    if market_errors:
        method += " 一部のマーケット材料を取得できなかったため、その材料の変化率は0%として表示しています。"

    return {
        "asOf": now.isoformat(timespec="seconds"),
        "forecastDate": now.strftime("%Y/%m/%d"),
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


def already_updated_for_slot(snapshot: dict, existing: dict | None) -> bool:
    if not existing:
        return False
    return (
        existing.get("currentSlot") == snapshot.get("currentSlot")
        and existing.get("forecastDate") == snapshot.get("forecastDate")
        and existing.get("fund", {}).get("navDate") == snapshot.get("fund", {}).get("navDate")
    )


def main() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing_snapshot()
    snapshot = build_snapshot()
    if already_updated_for_slot(snapshot, existing):
        print(f"Snapshot already updated for {snapshot['currentSlot']} on {snapshot['forecastDate']}")
        return
    DATA_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {DATA_PATH}")


if __name__ == "__main__":
    main()
