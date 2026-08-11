"""Shared normalization and processing pipeline for the market breadth dashboard.

Historical FinMind data is used once to create a bootstrap state and a baseline
CSV. Official TWSE/TPEx daily snapshots are then stored in one normalized raw
journal and replayed through the same calculation logic. Inserting a missed day
into the journal automatically recalculates every later dashboard row.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional

import requests

from sync_fallback_data import update_fallback_js


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
CACHE_DIR = BASE_DIR / "cache"
PRICE_DIR = CACHE_DIR / "prices"
MARGIN_DIR = CACHE_DIR / "margins"

MASTER_CSV = DATA_DIR / "daily_market_breadth.csv"
ROOT_CSV = BASE_DIR / "daily_market_breadth.csv"
BASELINE_CSV = DATA_DIR / "market_breadth_baseline.csv"
BOOTSTRAP_JSON = DATA_DIR / "processor_bootstrap.json"
RAW_DAILY_CSV = DATA_DIR / "raw_market_daily.csv"
RAW_TOTALS_CSV = DATA_DIR / "raw_market_totals.csv"
MANIFEST_JSON = DATA_DIR / "processing_manifest.json"
STOCK_TYPES_JSON = CACHE_DIR / "stock_types.json"

FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
START_DATE = "2024-01-01"
CALCULATION_VERSION = 2
MAINTENANCE_BASE = 166.6

CSV_HEADER = [
    "date",
    "taiex",
    "maint_130",
    "maint_140",
    "maint_150",
    "maint_160",
    "ma20_pct",
    "ma60_pct",
    "total_margin_ratio",
    "twse_margin_ratio",
    "tpex_margin_ratio",
]

RAW_HEADER = ["date", "stock_id", "market", "close", "margin_balance"]
TOTALS_HEADER = ["date", "margin_purchase_money"]
THRESHOLDS = (130, 140, 150, 160)


def parse_float(value) -> float:
    try:
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value or "").replace(",", "").strip()
        if cleaned in {"", "--", "---", "----"}:
            return 0.0
        return float(cleaned)
    except (TypeError, ValueError):
        return 0.0


def is_supported_stock(stock_id: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", str(stock_id or "").strip()))


def _read_json_list(path: Path) -> List[dict]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(content, encoding="utf-8", newline="")
    os.replace(temp_path, path)


def _atomic_write_json(path: Path, value) -> None:
    content = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    _atomic_write_text(path, content)


def _write_csv(path: Path, header: Iterable[str], rows: Iterable[Iterable]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(list(header))
        writer.writerows(rows)
    os.replace(temp_path, path)


def _load_csv_dicts(path: Path) -> List[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_finmind_token() -> str:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return os.getenv("FINMIND_TOKEN", "")
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == "FINMIND_TOKEN":
            return value.strip().strip("\"'")
    return os.getenv("FINMIND_TOKEN", "")


def _finmind_request(dataset: str, token: str, **params) -> List[dict]:
    query = {"dataset": dataset, **params}
    if token:
        query["token"] = token
    response = requests.get(FINMIND_API, params=query, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("msg") != "success" or not isinstance(payload.get("data"), list):
        raise RuntimeError(f"FinMind {dataset} failed: {payload.get('msg')}")
    return payload["data"]


def refresh_stock_types(token: Optional[str] = None) -> Dict[str, str]:
    """Refresh the stock market mapping, falling back to the local cache."""
    token = load_finmind_token() if token is None else token
    try:
        rows = _finmind_request("TaiwanStockInfo", token)
        mapping = {
            str(row.get("stock_id")): str(row.get("type"))
            for row in rows
            if is_supported_stock(str(row.get("stock_id", "")))
            and row.get("type") in {"twse", "tpex"}
        }
        if not mapping:
            raise RuntimeError("FinMind returned no supported TWSE/TPEx stocks")
        _atomic_write_json(STOCK_TYPES_JSON, mapping)
        return mapping
    except Exception as exc:
        if STOCK_TYPES_JSON.exists():
            print(f"[Warning] 股票市場別更新失敗，改用本機快取：{exc}")
            return json.loads(STOCK_TYPES_JSON.read_text(encoding="utf-8"))
        raise


def refresh_market_totals(token: Optional[str] = None) -> Dict[str, float]:
    """Refresh FinMind aggregate margin purchase money and persist it as raw data."""
    token = load_finmind_token() if token is None else token
    existing = load_market_totals()
    try:
        rows = _finmind_request(
            "TaiwanStockTotalMarginPurchaseShortSale",
            token,
            start_date=START_DATE,
        )
        for row in rows:
            if row.get("name") != "MarginPurchaseMoney" or not row.get("date"):
                continue
            value = parse_float(row.get("TodayBalance"))
            if value > 0:
                existing[str(row["date"])] = value
        _write_csv(
            RAW_TOTALS_CSV,
            TOTALS_HEADER,
            ([date, existing[date]] for date in sorted(existing)),
        )
    except Exception as exc:
        if not existing:
            raise
        print(f"[Warning] 市場融資金額更新失敗，改用已保存資料：{exc}")
    return existing


def load_market_totals() -> Dict[str, float]:
    return {
        row["date"]: parse_float(row.get("margin_purchase_money"))
        for row in _load_csv_dicts(RAW_TOTALS_CSV)
        if row.get("date") and parse_float(row.get("margin_purchase_money")) > 0
    }


def upsert_raw_day(
    trade_date: str,
    taiex: float,
    stock_rows: Iterable[Mapping[str, object]],
) -> None:
    """Replace one trading day's normalized raw snapshot in the journal."""
    retained = [row for row in _load_csv_dicts(RAW_DAILY_CSV) if row.get("date") != trade_date]
    normalized = [
        {
            "date": trade_date,
            "stock_id": "TAIEX",
            "market": "index",
            "close": taiex,
            "margin_balance": 0,
        }
    ]
    for row in stock_rows:
        stock_id = str(row.get("stock_id", "")).strip()
        market = str(row.get("market", "")).strip()
        close = parse_float(row.get("close"))
        margin_balance = parse_float(row.get("margin_balance"))
        if not is_supported_stock(stock_id) or market not in {"twse", "tpex"}:
            continue
        normalized.append(
            {
                "date": trade_date,
                "stock_id": stock_id,
                "market": market,
                "close": close,
                "margin_balance": margin_balance,
            }
        )

    all_rows = retained + normalized
    all_rows.sort(key=lambda row: (row["date"], row["stock_id"]))
    _write_csv(
        RAW_DAILY_CSV,
        RAW_HEADER,
        (
            [
                row["date"],
                row["stock_id"],
                row["market"],
                row["close"],
                row["margin_balance"],
            ]
            for row in all_rows
        ),
    )


def _new_stats(taiex: float) -> dict:
    return {
        "taiex": taiex,
        "maint_130": 0,
        "maint_140": 0,
        "maint_150": 0,
        "maint_160": 0,
        "ma20_above": 0,
        "ma20_tot": 0,
        "ma60_above": 0,
        "ma60_tot": 0,
        "margin_mval_all": 0.0,
        "margin_mval_twse": 0.0,
        "margin_mval_tpex": 0.0,
        "price_rows": 0,
        "margin_rows": 0,
    }


def _add_stock_to_stats(
    stats: MutableMapping[str, float],
    market: str,
    close: float,
    closes: Iterable[float],
    margin_balance: float,
) -> None:
    history = list(closes)
    if not history or close <= 0:
        return
    stats["price_rows"] += 1
    ma20_window = history[-20:]
    ma60_window = history[-60:]
    ma20 = sum(ma20_window) / len(ma20_window)
    ma60 = sum(ma60_window) / len(ma60_window)

    stats["ma20_tot"] += 1
    stats["ma60_tot"] += 1
    if close > ma20:
        stats["ma20_above"] += 1
    if close > ma60:
        stats["ma60_above"] += 1

    if margin_balance <= 0:
        return
    stats["margin_rows"] += 1
    maintenance_proxy = (close / ma20) * MAINTENANCE_BASE
    for threshold in THRESHOLDS:
        if maintenance_proxy < threshold:
            stats[f"maint_{threshold}"] += 1

    market_value = close * margin_balance * 1000
    stats["margin_mval_all"] += market_value
    if market == "twse":
        stats["margin_mval_twse"] += market_value
    elif market == "tpex":
        stats["margin_mval_tpex"] += market_value


def _finalize_row(trade_date: str, stats: Mapping[str, float], total_debt: float) -> List:
    if total_debt <= 0:
        raise RuntimeError(f"{trade_date} 缺少市場融資金額，拒絕產生不完整資料")

    ma20_pct = round(stats["ma20_above"] / stats["ma20_tot"] * 100, 1)
    ma60_pct = round(stats["ma60_above"] / stats["ma60_tot"] * 100, 1)
    market_value = stats["margin_mval_all"]
    tpex_market_value = stats["margin_mval_tpex"]

    # Preserve the historical estimator's calibration so baseline and daily
    # rows use one continuous scale. These are market proxies, not broker-level
    # account maintenance ratios.
    total_ratio = round((market_value / total_debt) * 80.2, 1)
    twse_ratio = round((market_value / total_debt) * 81.0, 1)
    tpex_ratio = round((tpex_market_value / (total_debt * 0.19)) * 60.7, 1)

    row = [
        trade_date,
        round(parse_float(stats["taiex"]), 2),
        int(stats["maint_130"]),
        int(stats["maint_140"]),
        int(stats["maint_150"]),
        int(stats["maint_160"]),
        ma20_pct,
        ma60_pct,
        total_ratio,
        twse_ratio,
        tpex_ratio,
    ]
    _validate_output_row(row)
    return row


def _validate_output_row(row: List) -> None:
    date = row[0]
    counts = [int(value) for value in row[2:6]]
    if counts != sorted(counts):
        raise RuntimeError(f"{date} 維持率門檻家數不是遞增序列：{counts}")
    if parse_float(row[1]) <= 0:
        raise RuntimeError(f"{date} 加權指數無效")
    if not all(0 <= parse_float(value) <= 100 for value in row[6:8]):
        raise RuntimeError(f"{date} 市場廣度超出 0~100%")
    if not all(parse_float(value) >= 50 for value in row[8:11]):
        raise RuntimeError(f"{date} 維持率估算值低於資料完整性門檻")


def _load_margin_map(path: Path, cutoff: str) -> Dict[str, float]:
    result = {}
    for row in _read_json_list(path):
        trade_date = str(row.get("date", ""))
        if trade_date and trade_date <= cutoff:
            balance = parse_float(
                row.get("MarginPurchaseTodayBalance")
                or row.get("MarginPurchaseBalance")
            )
            result[trade_date] = balance
    return result


def _raw_dates() -> List[str]:
    return sorted({row["date"] for row in _load_csv_dicts(RAW_DAILY_CSV) if row.get("date")})


def _choose_bootstrap_cutoff() -> str:
    taiex_rows = _read_json_list(PRICE_DIR / "TAIEX.json")
    taiex_dates = sorted({str(row.get("date")) for row in taiex_rows if row.get("date")})
    if not taiex_dates:
        raise RuntimeError("cache/prices/TAIEX.json 沒有可用日期")
    raw_dates = _raw_dates()
    if not raw_dates:
        return taiex_dates[-1]
    candidates = [date for date in taiex_dates if date < raw_dates[0]]
    if not candidates:
        raise RuntimeError("原始日誌之前沒有可建立基準的 TAIEX 快取")
    return candidates[-1]


def rebuild_baseline_from_cache(cutoff: Optional[str] = None) -> List[List]:
    """Rebuild the historical baseline and bootstrap state from FinMind caches."""
    cutoff = cutoff or _choose_bootstrap_cutoff()
    print(f"建立共用計算基準，截止日：{cutoff}")
    stock_types = refresh_stock_types()
    totals = refresh_market_totals()

    taiex_by_date = {
        str(row.get("date")): parse_float(row.get("close") or row.get("TAIEX"))
        for row in _read_json_list(PRICE_DIR / "TAIEX.json")
        if row.get("date") and str(row.get("date")) <= cutoff
    }
    daily_stats = {
        date: _new_stats(value)
        for date, value in taiex_by_date.items()
        if value > 0
    }
    bootstrap_stocks = {}

    price_files = sorted(PRICE_DIR.glob("*.json"))
    for index, price_path in enumerate(price_files, start=1):
        stock_id = price_path.stem
        if stock_id == "TAIEX" or not is_supported_stock(stock_id):
            continue
        # Keep delisted/historical four-digit securities in breadth and total
        # market calculations. FinMind's current stock list may no longer carry
        # their market type; the legacy calculation included those cache files.
        market = stock_types.get(stock_id, "unknown")
        price_by_date = {}
        for row in _read_json_list(price_path):
            trade_date = str(row.get("date", ""))
            close = parse_float(row.get("close"))
            if trade_date and trade_date <= cutoff and close > 0:
                price_by_date[trade_date] = close
        if not price_by_date:
            continue

        margin_by_date = _load_margin_map(MARGIN_DIR / f"{stock_id}.json", cutoff)
        rolling = deque(maxlen=60)
        last_date = ""
        for trade_date in sorted(price_by_date):
            close = price_by_date[trade_date]
            rolling.append(close)
            last_date = trade_date
            stats = daily_stats.get(trade_date)
            if stats is not None:
                _add_stock_to_stats(
                    stats,
                    market,
                    close,
                    rolling,
                    margin_by_date.get(trade_date, 0.0),
                )

        bootstrap_stocks[stock_id] = {
            "market": market,
            "last_date": last_date,
            "closes": list(rolling),
        }
        if index % 250 == 0:
            print(f"  已處理 {index}/{len(price_files)} 份個股快取")

    rows = []
    for trade_date in sorted(daily_stats):
        stats = daily_stats[trade_date]
        if stats["ma20_tot"] == 0 or stats["ma60_tot"] == 0:
            continue
        total_debt = totals.get(trade_date, 0.0)
        if total_debt <= 0:
            continue
        rows.append(_finalize_row(trade_date, stats, total_debt))

    if not rows or rows[-1][0] != cutoff:
        raise RuntimeError(f"基準資料未能完整產生至 {cutoff}")

    _write_csv(BASELINE_CSV, CSV_HEADER, rows)
    _atomic_write_json(
        BOOTSTRAP_JSON,
        {
            "version": CALCULATION_VERSION,
            "as_of": cutoff,
            "stocks": bootstrap_stocks,
        },
    )
    print(f"基準建立完成：{len(rows)} 個交易日、{len(bootstrap_stocks)} 檔股票")
    return process_raw_journal()


def _load_bootstrap() -> dict:
    if not BOOTSTRAP_JSON.exists() or not BASELINE_CSV.exists():
        rebuild_baseline_from_cache()
    payload = json.loads(BOOTSTRAP_JSON.read_text(encoding="utf-8"))
    if payload.get("version") != CALCULATION_VERSION:
        raise RuntimeError("處理器版本已變更，請重新建立 baseline")
    return payload


def process_raw_journal() -> List[List]:
    """Replay normalized daily snapshots and regenerate every public output."""
    bootstrap = _load_bootstrap()
    as_of = str(bootstrap["as_of"])
    totals = load_market_totals()
    baseline_rows = _load_csv_dicts(BASELINE_CSV)
    output_rows = [[row[column] for column in CSV_HEADER] for row in baseline_rows]

    state = {}
    for stock_id, value in bootstrap.get("stocks", {}).items():
        state[stock_id] = {
            "market": value["market"],
            "last_date": value.get("last_date", as_of),
            "closes": deque((parse_float(v) for v in value.get("closes", [])), maxlen=60),
        }

    grouped = defaultdict(list)
    for row in _load_csv_dicts(RAW_DAILY_CSV):
        if row.get("date") and row["date"] > as_of:
            grouped[row["date"]].append(row)

    diagnostics = {}
    for trade_date in sorted(grouped):
        rows = grouped[trade_date]
        index_rows = [row for row in rows if row.get("stock_id") == "TAIEX"]
        if len(index_rows) != 1:
            raise RuntimeError(f"{trade_date} 必須且只能有一筆 TAIEX 原始資料")
        stock_rows = [row for row in rows if row.get("stock_id") != "TAIEX"]
        twse_rows = [row for row in stock_rows if row.get("market") == "twse"]
        tpex_rows = [row for row in stock_rows if row.get("market") == "tpex"]
        price_count = sum(parse_float(row.get("close")) > 0 for row in stock_rows)
        margin_count = sum(parse_float(row.get("margin_balance")) > 0 for row in stock_rows)
        if len(twse_rows) < 700 or len(tpex_rows) < 500 or price_count < 1400 or margin_count < 700:
            raise RuntimeError(
                f"{trade_date} 原始資料不完整：TWSE={len(twse_rows)}, "
                f"TPEx={len(tpex_rows)}, prices={price_count}, margins={margin_count}"
            )

        stats = _new_stats(parse_float(index_rows[0].get("close")))
        for row in stock_rows:
            stock_id = row["stock_id"]
            market = row["market"]
            close = parse_float(row.get("close"))
            margin_balance = parse_float(row.get("margin_balance"))
            if close <= 0:
                continue
            stock_state = state.setdefault(
                stock_id,
                {"market": market, "last_date": "", "closes": deque(maxlen=60)},
            )
            stock_state["market"] = market
            if trade_date <= stock_state["last_date"]:
                raise RuntimeError(f"{trade_date} 原始日誌順序錯誤：{stock_id}")
            stock_state["closes"].append(close)
            stock_state["last_date"] = trade_date
            _add_stock_to_stats(
                stats,
                market,
                close,
                stock_state["closes"],
                margin_balance,
            )

        output_rows.append(_finalize_row(trade_date, stats, totals.get(trade_date, 0.0)))
        diagnostics[trade_date] = {
            "twse_rows": len(twse_rows),
            "tpex_rows": len(tpex_rows),
            "price_rows": int(stats["price_rows"]),
            "margin_rows": int(stats["margin_rows"]),
        }

    _validate_series(output_rows)
    _write_public_outputs(output_rows, diagnostics, as_of)
    return output_rows


def _validate_series(rows: List[List]) -> None:
    dates = [str(row[0]) for row in rows]
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        raise RuntimeError("輸出日期未遞增或含重複日期")
    for row in rows:
        _validate_output_row(row)


def _write_public_outputs(rows: List[List], diagnostics: dict, baseline_as_of: str) -> None:
    _write_csv(MASTER_CSV, CSV_HEADER, rows)
    shutil.copyfile(MASTER_CSV, ROOT_CSV)

    monthly = defaultdict(list)
    for row in rows:
        monthly[str(row[0])[:7]].append(row)
    for year_month, month_rows in monthly.items():
        year, month = year_month.split("-")
        month_path = DATA_DIR / year / month / f"market_breadth_{year_month}.csv"
        _write_csv(month_path, CSV_HEADER, month_rows)

    update_fallback_js()
    latest = rows[-1]
    _atomic_write_json(
        MANIFEST_JSON,
        {
            "calculation_version": CALCULATION_VERSION,
            "baseline_as_of": baseline_as_of,
            "data_through": latest[0],
            "row_count": len(rows),
            "latest": dict(zip(CSV_HEADER, latest)),
            "raw_diagnostics": diagnostics,
        },
    )
    print(
        f"共用後處理完成：{len(rows)} 筆，最新交易日 {latest[0]}，"
        f"<130%={latest[2]} 檔"
    )


def rebuild_all_outputs() -> List[List]:
    """Ensure a bootstrap exists, then replay every normalized raw day."""
    if not BOOTSTRAP_JSON.exists() or not BASELINE_CSV.exists():
        return rebuild_baseline_from_cache()
    return process_raw_journal()
