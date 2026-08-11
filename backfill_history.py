import os
import sys
import io
import json
import time
import requests

if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass
from dotenv import load_dotenv
from market_pipeline import rebuild_baseline_from_cache

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
    print("\n歷史資料下載完成，交由共用正規化後處理器重建基準與公開輸出...")
    rebuild_baseline_from_cache()

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
