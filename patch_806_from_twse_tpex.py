import os
import json
import urllib.request
import ssl
from backfill_history import calculate_and_export

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRICE_DIR = os.path.join(BASE_DIR, "cache", "prices")
MARGIN_DIR = os.path.join(BASE_DIR, "cache", "margins")

def fetch_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, context=ctx) as resp:
        return json.loads(resp.read().decode('utf-8'))

def parse_float(val):
    if not val or val == '--' or val == '----': return 0.0
    try:
        return float(str(val).replace(',', '').strip())
    except:
        return 0.0

def patch_806():
    print("=========================================")
    print(" 正在從 TWSE 及 TPEx 抓取 2026-08-06 盤後大包數據...")
    print("=========================================")
    
    # 1. 抓取 TWSE (上市) 2026-08-06 價格與融資數據
    url_twse_p = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY_ALL?date=20260806&response=json"
    url_twse_m = "https://www.twse.com.tw/rwd/zh/margin/MI_MARGN?date=20260806&selectType=ALL&response=json"
    
    twse_prices = {}
    twse_margins = {}
    
    try:
        data_p = fetch_json(url_twse_p)
        if data_p.get("stat") == "OK" and "data" in data_p:
            for r in data_p["data"]:
                code = r[0].strip()
                close_p = parse_float(r[8] if len(r) > 8 else 0)
                if close_p > 0:
                    twse_prices[code] = close_p
            print(f"-> TWSE 8/6 價格讀取成功 (共 {len(twse_prices)} 檔)")
    except Exception as e:
        print("TWSE 價格抓取失敗:", e)
        
    try:
        data_m = fetch_json(url_twse_m)
        if data_m.get("stat") == "OK" and "tables" in data_m and len(data_m["tables"]) > 0:
            for r in data_m["tables"][0].get("data", []):
                code = r[0].strip()
                bal_shares = parse_float(r[6] if len(r) > 6 else 0) # 融資今日餘額(張)
                if bal_shares > 0:
                    twse_margins[code] = bal_shares
            print(f"-> TWSE 8/6 融資餘額讀取成功 (共 {len(twse_margins)} 檔)")
    except Exception as e:
        print("TWSE 融資抓取失敗:", e)
        
    # 2. 抓取 TPEx (上櫃) 2026-08-06 價格與融資數據
    url_tpex_p = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&d=115/08/06&o=json"
    url_tpex_m = "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&d=115/08/06&o=json"
    
    tpex_prices = {}
    tpex_margins = {}
    
    try:
        data_p = fetch_json(url_tpex_p)
        if "aaData" in data_p:
            for r in data_p["aaData"]:
                code = r[0].strip()
                close_p = parse_float(r[2] if len(r) > 2 else 0)
                if close_p > 0:
                    tpex_prices[code] = close_p
            print(f"-> TPEx 8/6 價格讀取成功 (共 {len(tpex_prices)} 檔)")
    except Exception as e:
        print("TPEx 價格抓取失敗:", e)
        
    try:
        data_m = fetch_json(url_tpex_m)
        if "aaData" in data_m:
            for r in data_m["aaData"]:
                code = r[0].strip()
                bal_shares = parse_float(r[6] if len(r) > 6 else 0)
                if bal_shares > 0:
                    tpex_margins[code] = bal_shares
            print(f"-> TPEx 8/6 融資餘額讀取成功 (共 {len(tpex_margins)} 檔)")
    except Exception as e:
        print("TPEx 融資抓取失敗:", e)
        
    # 合併兩市 8/6 價格與融資
    all_prices_806 = {**twse_prices, **tpex_prices}
    all_margins_806 = {**twse_margins, **tpex_margins}
    
    print(f"8/6 全市場彙整完成：價格股票 {len(all_prices_806)} 檔, 融資股票 {len(all_margins_806)} 檔")
    
    # 3. 更新 local快照快取 cache/prices 與 cache/margins
    patched_count = 0
    price_files = [f for f in os.listdir(PRICE_DIR) if f.endswith('.json')]
    
    for pfile in price_files:
        stock_id = pfile.replace(".json", "")
        if stock_id == "TAIEX": continue
        
        ppath = os.path.join(PRICE_DIR, pfile)
        mpath = os.path.join(MARGIN_DIR, f"{stock_id}.json")
        
        # 補價格
        pdata = []
        if os.path.exists(ppath):
            with open(ppath, 'r', encoding='utf-8') as f:
                pdata = json.load(f)
        
        p_dates = {r.get("date") for r in pdata if "date" in r}
        if "2026-08-06" not in p_dates and stock_id in all_prices_806:
            pdata.append({
                "date": "2026-08-06",
                "stock_id": stock_id,
                "close": all_prices_806[stock_id]
            })
            with open(ppath, 'w', encoding='utf-8') as f:
                json.dump(pdata, f)
            patched_count += 1
            
        # 補融資
        mdata = []
        if os.path.exists(mpath):
            with open(mpath, 'r', encoding='utf-8') as f:
                mdata = json.load(f)
        
        m_dates = {r.get("date") for r in mdata if "date" in r}
        if "2026-08-06" not in m_dates and stock_id in all_margins_806:
            mdata.append({
                "date": "2026-08-06",
                "stock_id": stock_id,
                "MarginPurchaseTodayBalance": all_margins_806[stock_id]
            })
            with open(mpath, 'w', encoding='utf-8') as f:
                json.dump(mdata, f)
                
    print(f"成功將 2026-08-06 資料補入 {patched_count} 檔股票快照！")
    
    # 4. 重新計算並導出 CSV & data_fallback.js
    calculate_and_export()

if __name__ == "__main__":
    patch_806()
