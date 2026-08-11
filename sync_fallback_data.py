"""
將 daily_market_breadth.csv 自動轉為 data_fallback.js
解決直接雙擊開啟 index.html 時因 file:// CORS 政策導致無法 fetch 外部檔案的問題。
"""

import os
import shutil

BASE_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE_DIR, "data", "daily_market_breadth.csv")
FALLBACK_JS_PATH = os.path.join(BASE_DIR, "data_fallback.js")
ROOT_CSV_PATH = os.path.join(BASE_DIR, "daily_market_breadth.csv")

def update_fallback_js():
    if not os.path.exists(CSV_PATH):
        # 備用路徑
        CSV_PATH_ALT = os.path.join(BASE_DIR, "daily_market_breadth.csv")
        if os.path.exists(CSV_PATH_ALT):
            csv_file = CSV_PATH_ALT
        else:
            print("未找到 CSV 檔案")
            return
    else:
        csv_file = CSV_PATH

    with open(csv_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # 根目錄 CSV 是相容性鏡像；不可再保留不同欄位或不同日期的舊資料。
    if os.path.abspath(csv_file) != os.path.abspath(ROOT_CSV_PATH):
        shutil.copyfile(csv_file, ROOT_CSV_PATH)

    js_content = f"window.FALLBACK_CSV = `{content}`;\n"

    with open(FALLBACK_JS_PATH, 'w', encoding='utf-8') as f:
        f.write(js_content)

    print(f"成功同步至 data_fallback.js ({len(content)} 位元組)")

if __name__ == "__main__":
    update_fallback_js()
