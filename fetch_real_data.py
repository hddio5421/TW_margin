"""Download one official TWSE/TPEx trading day and rebuild dashboard data.

Both normal daily updates and missed-day backfills are normalized into
``data/raw_market_daily.csv``. The shared processor then replays all raw days
after the historical bootstrap, so calculation rules never change at the join.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional

import requests

from market_pipeline import (
    is_supported_stock,
    parse_float,
    rebuild_all_outputs,
    rebuild_baseline_from_cache,
    refresh_market_totals,
    upsert_raw_day,
)


if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}

TWSE_PRICE_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
TWSE_MARGIN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
TPEX_PRICE_URL = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes"
TPEX_MARGIN_URL = "https://www.tpex.org.tw/www/zh-tw/margin/balance"
TPEX_LATEST_URL = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_margin_balance"


def fetch_json(url: str, params: Optional[dict] = None, retries: int = 5):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, params=params, headers=HEADERS, timeout=90)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_error = exc
            if attempt == retries:
                break
            wait_seconds = 3 * attempt
            print(f"[Warning] {url} 讀取失敗，{wait_seconds} 秒後重試 ({attempt}/{retries})：{exc}")
            time.sleep(wait_seconds)
    raise RuntimeError(f"{url} 經過 {retries} 次重試仍失敗：{last_error}")


def roc_compact_to_iso(value: str) -> str:
    raw = str(value or "").strip().replace("/", "")
    if len(raw) != 7 or not raw.isdigit():
        raise ValueError(f"無法辨識民國日期：{value}")
    return f"{int(raw[:3]) + 1911:04d}-{raw[3:5]}-{raw[5:7]}"


def discover_latest_trade_date() -> str:
    rows = fetch_json(TPEX_LATEST_URL)
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("TPEx 最新融資 API 沒有資料")
    dates = {
        roc_compact_to_iso(row.get("Date"))
        for row in rows
        if isinstance(row, dict) and row.get("Date")
    }
    if len(dates) != 1:
        raise RuntimeError(f"TPEx 最新融資 API 日期不一致：{sorted(dates)}")
    return dates.pop()


def _find_table(payload: Mapping, required_fields: Iterable[str], title_text: str = "") -> dict:
    required = set(required_fields)
    for table in payload.get("tables", []):
        fields = set(table.get("fields", []))
        title = str(table.get("title", ""))
        if required.issubset(fields) and (not title_text or title_text in title):
            return table
    raise RuntimeError(f"找不到欄位 {sorted(required)} 的資料表")


def _field_index(table: Mapping, field_name: str) -> int:
    try:
        return list(table.get("fields", [])).index(field_name)
    except ValueError as exc:
        raise RuntimeError(f"資料表缺少欄位：{field_name}") from exc


def _parse_twse_price(payload: Mapping) -> tuple[Dict[str, float], float]:
    table = _find_table(payload, {"證券代號", "收盤價"}, "每日收盤行情")
    code_index = _field_index(table, "證券代號")
    close_index = _field_index(table, "收盤價")
    prices = {}
    for row in table.get("data", []):
        code = str(row[code_index]).strip()
        close = parse_float(row[close_index])
        if is_supported_stock(code) and close > 0:
            prices[code] = close

    index_table = _find_table(payload, {"指數", "收盤指數"}, "價格指數")
    name_index = _field_index(index_table, "指數")
    value_index = _field_index(index_table, "收盤指數")
    taiex = 0.0
    for row in index_table.get("data", []):
        if str(row[name_index]).strip() == "發行量加權股價指數":
            taiex = parse_float(row[value_index])
            break
    if taiex <= 0:
        raise RuntimeError("TWSE 資料中找不到有效的發行量加權股價指數")
    return prices, taiex


def _parse_twse_margin(payload: Mapping) -> Dict[str, float]:
    table = None
    for candidate in payload.get("tables", []):
        if "融資融券彙總" in str(candidate.get("title", "")):
            table = candidate
            break
    if table is None:
        raise RuntimeError("TWSE 資料中找不到融資融券彙總表")

    balances = {}
    for row in table.get("data", []):
        if len(row) < 7:
            continue
        code = str(row[0]).strip()
        balance = parse_float(row[6])
        if is_supported_stock(code):
            balances[code] = balance
    return balances


def _parse_tpex_price(payload: Mapping) -> Dict[str, float]:
    table = _find_table(payload, {"代號", "收盤"}, "上櫃股票行情")
    code_index = _field_index(table, "代號")
    close_index = _field_index(table, "收盤")
    prices = {}
    for row in table.get("data", []):
        code = str(row[code_index]).strip()
        close = parse_float(row[close_index])
        if is_supported_stock(code) and close > 0:
            prices[code] = close
    return prices


def _parse_tpex_margin(payload: Mapping) -> Dict[str, float]:
    table = _find_table(payload, {"代號", "資餘額"}, "融資融券餘額")
    code_index = _field_index(table, "代號")
    balance_index = _field_index(table, "資餘額")
    balances = {}
    for row in table.get("data", []):
        code = str(row[code_index]).strip()
        balance = parse_float(row[balance_index])
        if is_supported_stock(code):
            balances[code] = balance
    return balances


def _validate_response_date(payload: Mapping, expected: str, source: str) -> None:
    raw = str(payload.get("date", "")).replace("-", "").replace("/", "")
    expected_compact = expected.replace("-", "")
    if raw != expected_compact:
        raise RuntimeError(f"{source} 回傳日期 {raw or '(空白)'}，預期 {expected_compact}")
    stat = str(payload.get("stat", "")).lower()
    if stat not in {"ok"}:
        raise RuntimeError(f"{source} 回傳狀態不是 OK：{payload.get('stat')}")


def fetch_official_day(trade_date: str) -> tuple[float, List[dict]]:
    parsed = datetime.strptime(trade_date, "%Y-%m-%d").date()
    compact = parsed.strftime("%Y%m%d")
    slash_date = parsed.strftime("%Y/%m/%d")

    print(f"下載 {trade_date} TWSE 收盤行情與融資餘額...")
    twse_price_payload = fetch_json(
        TWSE_PRICE_URL,
        {"date": compact, "type": "ALLBUT0999", "response": "json"},
    )
    twse_margin_payload = fetch_json(
        TWSE_MARGIN_URL,
        {"date": compact, "selectType": "ALL", "response": "json"},
    )

    print(f"下載 {trade_date} TPEx 收盤行情與融資餘額...")
    tpex_price_payload = fetch_json(
        TPEX_PRICE_URL,
        {"date": slash_date, "id": "", "response": "json"},
    )
    tpex_margin_payload = fetch_json(
        TPEX_MARGIN_URL,
        {"date": slash_date, "id": "", "response": "json"},
    )

    for payload, source in (
        (twse_price_payload, "TWSE 收盤"),
        (twse_margin_payload, "TWSE 融資"),
        (tpex_price_payload, "TPEx 收盤"),
        (tpex_margin_payload, "TPEx 融資"),
    ):
        _validate_response_date(payload, trade_date, source)

    twse_prices, taiex = _parse_twse_price(twse_price_payload)
    twse_margins = _parse_twse_margin(twse_margin_payload)
    tpex_prices = _parse_tpex_price(tpex_price_payload)
    tpex_margins = _parse_tpex_margin(tpex_margin_payload)

    if len(twse_prices) < 700 or len(twse_margins) < 700:
        raise RuntimeError(
            f"TWSE 資料不完整：prices={len(twse_prices)}, margins={len(twse_margins)}"
        )
    if len(tpex_prices) < 500 or len(tpex_margins) < 500:
        raise RuntimeError(
            f"TPEx 資料不完整：prices={len(tpex_prices)}, margins={len(tpex_margins)}"
        )

    normalized = []
    for market, prices, margins in (
        ("twse", twse_prices, twse_margins),
        ("tpex", tpex_prices, tpex_margins),
    ):
        for stock_id in sorted(set(prices) | set(margins)):
            normalized.append(
                {
                    "stock_id": stock_id,
                    "market": market,
                    "close": prices.get(stock_id, 0.0),
                    "margin_balance": margins.get(stock_id, 0.0),
                }
            )

    print(
        f"官方資料驗證完成：TAIEX={taiex:,.2f}, TWSE={len(twse_prices)} 檔, "
        f"TPEx={len(tpex_prices)} 檔"
    )
    return taiex, normalized


def process_and_update(target_date: Optional[str] = None) -> List:
    trade_date = target_date or discover_latest_trade_date()
    datetime.strptime(trade_date, "%Y-%m-%d")
    print("=" * 58)
    print(f"台股原始資料標準化與共用後處理：{trade_date}")
    print("=" * 58)

    taiex, stock_rows = fetch_official_day(trade_date)
    # No project file is changed until all four official datasets pass validation.
    upsert_raw_day(trade_date, taiex, stock_rows)
    totals = refresh_market_totals()
    if trade_date not in totals:
        raise RuntimeError(f"FinMind 尚未提供 {trade_date} 的市場融資金額")
    rows = rebuild_all_outputs()
    latest = rows[-1]
    if latest[0] < trade_date:
        raise RuntimeError(f"處理後資料只到 {latest[0]}，未到目標日期 {trade_date}")
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="下載官方盤後資料；可指定日期回補，並以共用公式重算後續資料。"
    )
    parser.add_argument(
        "--date",
        dest="trade_date",
        metavar="YYYY-MM-DD",
        help="指定要下載或回補的交易日；省略時自動使用最新交易日。",
    )
    parser.add_argument(
        "--rebuild-only",
        action="store_true",
        help="不下載資料，只重播既有原始日誌並重建所有輸出。",
    )
    parser.add_argument(
        "--rebuild-baseline",
        action="store_true",
        help="從既有 FinMind 快取重建歷史基準，再重播所有官方原始日誌。",
    )
    args = parser.parse_args()

    try:
        if args.rebuild_baseline:
            latest = rebuild_baseline_from_cache()[-1]
        elif args.rebuild_only:
            latest = rebuild_all_outputs()[-1]
        else:
            latest = process_and_update(args.trade_date)
        print(
            f"完成：{latest[0]} TAIEX={float(latest[1]):,.2f}, "
            f"<130%={latest[2]} 檔"
        )
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
