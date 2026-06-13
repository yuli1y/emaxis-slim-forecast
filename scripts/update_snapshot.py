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
FUND_CSV_URL = "https://www.am.mufg.jp/fund_file/setteirai/253425.csv"
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


def fetch_fund_data_from_csv() -> list[dict]:
    headers = {
        "User-Agent": "Mozilla/5.0 emaxis-slim-forecast/1.0",
    }
    request = urllib.request.Request(
        FUND_CSV_URL,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        content = response.read().decode("shift_jis")

    lines = content.splitlines()
    data_points = []
    # Line 0 is the title, line 1 is headers. Data starts from line 2.
    for line in lines[2:]:
        if not line.strip():
            continue
        parts = line.split(",")
        if len(parts) < 2:
            continue
        date_str = parts[0].strip()  # YYYY/MM/DD
        nav_str = parts[1].strip()   # 基準価額(円)
        if not date_str or not nav_str:
            continue
        try:
            nav = int(nav_str)
            data_points.append({
                "date": date_str,
                "value": nav,
            })
        except ValueError:
            continue
    return data_points


def latest_fund_price(data_points: list[dict]) -> dict:
    if len(data_points) < 2:
        raise RuntimeError("三菱UFJアセットマネジメントのCSVから十分なデータを取得できませんでした")
    
    latest = data_points[-1]
    prev = data_points[-2]
    
    nav = float(latest["value"])
    prev_nav = float(prev["value"])
    change = nav - prev_nav
    change_rate = change / prev_nav
    
    return {
        "symbol": FUND_CODE,
        "date": latest["date"],
        "value": nav,
        "previousValue": prev_nav,
        "return": change_rate,
        "change": change,
        "source": "三菱UFJアセットマネジメント",
        "jwtToken": "",
    }


def fund_history(fund: dict, data_points: list[dict]) -> list[dict]:
    # Extract historical points (last 31 entries) and map keys/formats
    history = []
    for dp in data_points[-31:]:
        history.append({
            "date": dp["date"].replace("/", "-"),
            "value": float(dp["value"])
        })
    return history


def estimate(slot_hour: int, fund: dict, acwi: dict, fx: dict) -> dict:
    combined_return = acwi["return"] + fx["return"]
    predicted = fund["value"] * (1 + combined_return)
    return {
        "slot": f"{slot_hour:02d}:00",
        "status": "ready",
        "predictedNav": round(predicted),
        "change": round(predicted - fund["value"]),
        "changePct": combined_return,
        "estimatedErrorYen": round(predicted * ESTIMATED_ERROR_PCT),
        "estimatedErrorPct": ESTIMATED_ERROR_PCT,
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
        "estimatedErrorYen": None,
        "estimatedErrorPct": ESTIMATED_ERROR_PCT,
        "drivers": {
            "acwiReturn": None,
            "fxReturn": None,
        },
    }


def active_slot(now: datetime) -> str:
    if 10 <= now.hour < 18:
        return "10:00"
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
    forecast_date = next_business_date(fund["date"])
    forecasts = {
        "10:00": pending_forecast("10:00", f"{forecast_date} 10:00更新後に表示します。"),
        "18:00": pending_forecast("18:00", f"{forecast_date} 18:00更新後に表示します。"),
    }

    existing = load_existing_snapshot()
    if current_slot != "next" and existing and existing.get("fund", {}).get("navDate") == fund["date"]:
        for forecast in existing.get("forecasts", []):
            if forecast.get("slot") in forecasts and forecast.get("status") == "ready":
                forecasts[forecast["slot"]] = forecast

    if current_slot == "10:00":
        forecasts["10:00"] = estimate(10, fund, acwi, fx)
        forecasts["18:00"] = pending_forecast("18:00", f"{forecast_date} 18:00更新後に表示します。")
    elif current_slot == "18:00":
        forecasts["18:00"] = estimate(18, fund, acwi, fx)

    return [forecasts["10:00"], forecasts["18:00"]]


def build_snapshot() -> dict:
    data_points = fetch_fund_data_from_csv()
    fund = latest_fund_price(data_points)
    history = fund_history(fund, data_points)
    acwi = latest_market_price(ACWI_SYMBOL, "ACWI ETF")
    fx = latest_market_price(FX_SYMBOL, "USD/JPY")
    now = datetime.now(JST)
    slot = active_slot(now)
    market_errors = [item["error"] for item in (acwi, fx) if item.get("error")]

    method = (
        "直近の基準価額に、ACWI ETF(米ドル建て)の日次変化率とドル円の日次変化率を"
        "単純加算して掛けた参考推計です。実際の採用為替、評価タイミング、組入差、ETF固有要因は未調整です。"
        f" 目安として推計値の±{ESTIMATED_ERROR_PCT:.0%}程度ずれる可能性があります。"
    )
    if market_errors:
        method += " 一部のマーケット材料を取得できなかったため、その材料の変化率は0%として表示しています。"

    return {
        "asOf": now.isoformat(timespec="seconds"),
        "forecastDate": next_business_date(fund["date"]),
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
