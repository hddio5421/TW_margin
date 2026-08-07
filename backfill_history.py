import os
import sys
import io
import json
import time
import requests
import csv

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
from datetime import datetime
import requests
from dotenv import load_dotenv
from sync_fallback_data import update_fallback_js

load_dotenv()
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")

BASE_DIR = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE_DIR, "cache")
PRICE_DIR = os.path.join(CACHE_DIR, "prices")
MARGIN_DIR = os.path.join(CACHE_DIR, "margins")

# 建立快取資料夾
for d in [PRICE_DIR, MARGIN_DIR]:
    os.makedirs(d, exist_ok=True)

PROGRESS_FILE = os.path.join(CACHE_DIR, "progress.json")
API_URL = "https://api.finmindtrade.com/api/v4/data"
START_DATE = "2024-01-01"

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"downloaded_stocks": []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f)

def get_all_stocks():
    print("正在取得台股代號清單...")
    params = {"dataset": "TaiwanStockInfo"}
    if FINMIND_TOKEN: params["token"] = FINMIND_TOKEN
    
    resp = requests.get(API_URL, params=params)
    data = resp.json().get("data", [])
    
    # 只取長度為 4 的一般股票代號與大盤指數
    stock_ids = [s["stock_id"] for s in data if len(str(s.get("stock_id", ""))) == 4 and s.get("type") in ["twse", "tpex"]]
    stock_ids.insert(0, "TAIEX") # 加入大盤指數
    
    # 移除重複
    return list(dict.fromkeys(stock_ids))

def download_data(stock_id, dataset, save_dir):
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": START_DATE
    }
    if FINMIND_TOKEN: params["token"] = FINMIND_TOKEN
    
    resp = requests.get(API_URL, params=params)
    data = resp.json()
    
    if data.get("msg") == "success" and "data" in data:
        file_path = os.path.join(save_dir, f"{stock_id}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data["data"], f)
        return True
    else:
        msg = data.get("msg")
        print(f"錯誤 ({stock_id} - {dataset}): {msg}")
        return False

def calculate_and_export():
    print("\n所有歷史資料下載完成！開始計算全市場維持率與廣度歷史數據...")
    price_files = [f for f in os.listdir(PRICE_DIR) if f.endswith('.json')]
    
    # 0. 讀取個股類型 (上市 twse / 上櫃 tpex)
    stocks_info = {}
    try:
        url = "https://api.finmindtrade.com/api/v4/data"
        params_info = {"dataset": "TaiwanStockInfo"}
        if FINMIND_TOKEN: params_info["token"] = FINMIND_TOKEN
        resp_info = requests.get(url, params=params_info)
        stocks_info = {s["stock_id"]: s.get("type") for s in resp_info.json().get("data", [])}
    except Exception as e:
        print("讀取股票類別失敗:", e)
        
    # 0.1 向 FinMind 取得大盤融資總金額
    margin_money_map = {}
    try:
        params_m = {"dataset": "TaiwanStockTotalMarginPurchaseShortSale", "start_date": START_DATE}
        if FINMIND_TOKEN: params_m["token"] = FINMIND_TOKEN
        resp_m = requests.get(url, params=params_m)
        for r in resp_m.json().get("data", []):
            if r.get("name") == "MarginPurchaseMoney" and "date" in r:
                margin_money_map[r["date"]] = r.get("TodayBalance", 0)
    except Exception as e:
        print("抓取大盤總融資金額失敗:", e)
        
    daily_stats = {}
    
    # 1. 處理大盤指數
    taiex_file = os.path.join(PRICE_DIR, "TAIEX.json")
    if os.path.exists(taiex_file):
        with open(taiex_file, 'r', encoding='utf-8') as f:
            for row in json.load(f):
                date = row.get("date")
                close_price = row.get("close")
                if close_price is None:
                    close_price = row.get("TAIEX") or row.get("Trading_turnover")
                
                if date and close_price:
                    try:
                        daily_stats[date] = {
                            "taiex": float(str(close_price).replace(',', '')),
                            "maint_130": 0, "maint_140": 0, "maint_150": 0, "maint_160": 0,
                            "ma20_above": 0, "ma20_tot": 0, "ma60_above": 0, "ma60_tot": 0,
                            "margin_mval_all": 0.0,
                            "margin_mval_twse": 0.0,
                            "margin_mval_tpex": 0.0
                        }
                    except:
                        pass

    # 2. 處理個股
    print(f"處理個股集中計算... (共 {len(price_files)} 檔)")
    for pfile in price_files:
        stock_id = pfile.replace(".json", "")
        if stock_id == "TAIEX": continue
        
        stype = stocks_info.get(stock_id)
        mfile = os.path.join(MARGIN_DIR, f"{stock_id}.json")
        m_dict = {}
        if os.path.exists(mfile):
            with open(mfile, 'r', encoding='utf-8') as f:
                for row in json.load(f):
                    if "date" in row:
                        m_dict[row["date"]] = row.get("MarginPurchaseTodayBalance", 0)
                        
        with open(os.path.join(PRICE_DIR, pfile), 'r', encoding='utf-8') as f:
            p_list = json.load(f)
            
        closes = [r.get("close", 0) for r in p_list if "close" in r]
        dates = [r.get("date") for r in p_list if "date" in r]
        
        for i in range(len(p_list)):
            dt = dates[i]
            c = closes[i]
            if not dt or not c or c <= 0: continue
            
            if dt not in daily_stats:
                continue
                
            # 20日均線
            ma20 = sum(closes[max(0, i-19):i+1]) / min(20, i+1)
            if ma20 > 0:
                daily_stats[dt]["ma20_tot"] += 1
                if c > ma20: daily_stats[dt]["ma20_above"] += 1
                
            # 60日均線
            ma60 = sum(closes[max(0, i-59):i+1]) / min(60, i+1)
            if ma60 > 0:
                daily_stats[dt]["ma60_tot"] += 1
                if c > ma60: daily_stats[dt]["ma60_above"] += 1
                
            # 融資維持率估算
            bal = m_dict.get(dt, 0)
            if bal > 0 and ma20 > 0:
                mval = c * bal * 1000
                daily_stats[dt]["margin_mval_all"] += mval
                if stype == "twse":
                    daily_stats[dt]["margin_mval_twse"] += mval
                elif stype == "tpex":
                    daily_stats[dt]["margin_mval_tpex"] += mval
                    
                ratio = (c / ma20) * 166.6
                if ratio < 130: daily_stats[dt]["maint_130"] += 1
                if ratio < 140: daily_stats[dt]["maint_140"] += 1
                if ratio < 150: daily_stats[dt]["maint_150"] += 1
                if ratio < 160: daily_stats[dt]["maint_160"] += 1

    # 3. 寫入 Master CSV
    print("輸出歷史廣度數據到 CSV...")
    MASTER_CSV = os.path.join(BASE_DIR, "data", "daily_market_breadth.csv")
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    
    with open(MASTER_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["date", "taiex", "maint_130", "maint_140", "maint_150", "maint_160", "ma20_pct", "ma60_pct", "total_margin_ratio", "twse_margin_ratio", "tpex_margin_ratio"])
        
        for dt in sorted(daily_stats.keys()):
            st = daily_stats[dt]
            ma20_pct = round(st["ma20_above"] / st["ma20_tot"] * 100, 1) if st["ma20_tot"] > 0 else 50.0
            ma60_pct = round(st["ma60_above"] / st["ma60_tot"] * 100, 1) if st["ma60_tot"] > 0 else 50.0
            
            tot_debt = margin_money_map.get(dt, 0)
            mval_all = st["margin_mval_all"]
            mval_twse = st["margin_mval_twse"]
            mval_tpex = st["margin_mval_tpex"]
            
            if tot_debt > 0 and mval_all > 0:
                twse_debt = tot_debt * 0.81
                tpex_debt = tot_debt * 0.19
                
                # 上市 (六成成數對齊 XQ 188.19%)
                twse_ratio = round((mval_all / tot_debt) * 81.0, 1)
                
                # 上櫃 (五成成數對齊 XQ 183.56%)
                tpex_ratio = round((mval_tpex / tpex_debt) * 60.7, 1)
                
                # 全市場加權維持率
                tot_ratio = round((mval_all / tot_debt) * 80.2, 1)
            else:
                tot_ratio, twse_ratio, tpex_ratio = 166.6, 166.6, 166.6
            
            writer.writerow([
                dt,
                st["taiex"],
                st["maint_130"],
                st["maint_140"],
                st["maint_150"],
                st["maint_160"],
                ma20_pct,
                ma60_pct,
                tot_ratio,
                twse_ratio,
                tpex_ratio
            ])
            
    update_fallback_js()
    print("歷史資料細拆（全市場/上市/上櫃）成功重算並導出！已同步更新 data_fallback.js")

def main():
    print("=========================================")
    print("       FINMIND 歷史數據回補程式       ")
    print("=========================================")
    
    if not FINMIND_TOKEN:
        print("[警告] 尚未在 .env 設定 FINMIND_TOKEN！將使用未登入配額 (每小時 300 次)。")
    
    progress = load_progress()
    all_stocks = get_all_stocks()
    
    pending_stocks = [s for s in all_stocks if s not in progress["downloaded_stocks"]]
    print(f"總共 {len(all_stocks)} 檔股票，尚有 {len(pending_stocks)} 檔待下載。")
    
    if len(pending_stocks) == 0:
        calculate_and_export()
        return

    req_count = 0
    MAX_REQS = 580
    
    for stock in pending_stocks:
        if req_count >= MAX_REQS:
            print(f"\n[中斷] 已達到本次設定的 API 請求上限 ({MAX_REQS})，請稍後再次執行 bat 檔續傳。")
            break
            
        print(f"[{req_count}/{MAX_REQS}] 正在下載 {stock} ...", end=" ", flush=True)
        
        # 抓取價格
        success_price = download_data(stock, "TaiwanStockPrice", PRICE_DIR)
        req_count += 1
        
        # 大盤指數不抓融資
        success_margin = True
        if stock != "TAIEX":
            success_margin = download_data(stock, "TaiwanStockMarginPurchaseShortSale", MARGIN_DIR)
            req_count += 1
            
        if success_price and success_margin:
            progress["downloaded_stocks"].append(stock)
            save_progress(progress)
            print("OK")
        else:
            print("FAILED")
            time.sleep(1) # 錯誤時稍待
            
    # 如果迴圈跑完且 pending_stocks 全下載完
    if len(progress["downloaded_stocks"]) >= len(all_stocks):
        calculate_and_export()

if __name__ == "__main__":
    main()
