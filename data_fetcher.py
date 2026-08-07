"""
台股市場廣度與融資維持率資料處理腳本 (TWSE Margin Maintenance & Market Breadth Data Fetcher/Generator)
"""

import json
import random
import math
from datetime import datetime, timedelta

def generate_mock_historical_data(days=600):
    """
    生成真實感強烈的台股歷史數據，包含：
    1. 加權指數 (TAIEX)
    2. 各門檻 (<130%, <140%, <150%, <160%) 個股融資低維持率家數
    3. 全市場廣度 (% > 20MA, % > 60MA)
    4. 大盤整體融資維持率 %
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days * 7 // 5) # 考慮交易日
    
    dates = []
    taiex = []
    maint_130 = []
    maint_140 = []
    maint_150 = []
    maint_160 = []
    breadth_20ma = []
    breadth_60ma = []
    total_margin_ratio = []
    
    current_date = start_date
    current_taiex = 16500.0
    
    # 模擬波段震盪與回檔斷頭事件
    panic_phase = 0
    panic_intensity = 0.0
    
    trade_day_count = 0
    while trade_day_count < days:
        # 跳過週末
        if current_date.weekday() in (5, 6):
            current_date += timedelta(days=1)
            continue
            
        date_str = current_date.strftime("%Y-%m-%d")
        dates.append(date_str)
        
        # 偶爾觸發市場回檔/斷頭潮 (Panic event)
        if panic_phase == 0 and random.random() < 0.018 and trade_day_count > 40:
            panic_phase = random.randint(12, 28) # 恐慌持續天數
            panic_intensity = random.uniform(1.8, 3.8)
            
        if panic_phase > 0:
            # 恐慌下跌期
            change_pct = random.gauss(-0.018 * panic_intensity, 0.012)
            panic_phase -= 1
        else:
            # 常規波動與多頭上漲
            change_pct = random.gauss(0.0009, 0.008)
            
        current_taiex = max(8000.0, current_taiex * (1 + change_pct))
        taiex.append(round(current_taiex, 2))
        
        # 計算動態維持率與市場廣度
        # 當大盤大跌時，低維持率家數會呈暴增 (Spike)
        if change_pct < -0.015:
            spike_base = int(abs(change_pct) * 30000 * random.uniform(0.8, 1.2))
        elif change_pct < 0:
            spike_base = int(abs(change_pct) * 9000 * random.uniform(0.5, 1.0))
        else:
            spike_base = int(random.uniform(5, 45))
            
        # 根據跌幅模擬各門檻家數
        c_130 = max(2, int(spike_base * 0.4 + random.randint(0, 15)))
        c_140 = max(c_130 + 8, int(spike_base * 0.85 + random.randint(10, 30)))
        c_150 = max(c_140 + 15, int(spike_base * 1.35 + random.randint(30, 80)))
        c_160 = max(c_150 + 25, int(spike_base * 2.1 + random.randint(80, 150)))
        
        maint_130.append(c_130)
        maint_140.append(c_140)
        maint_150.append(c_150)
        maint_160.append(c_160)
        
        # 市場廣度 % (站上 20MA / 60MA)
        base_b20 = 55.0 + (change_pct * 1600)
        base_b20 = max(4.0, min(96.0, base_b20 + random.uniform(-8, 8)))
        
        base_b60 = 58.0 + (change_pct * 900)
        base_b60 = max(8.0, min(92.0, base_b60 + random.uniform(-4, 4)))
        
        breadth_20ma.append(round(base_b20, 1))
        breadth_60ma.append(round(base_b60, 1))
        
        # 大盤整體融資維持率 % (平時約 165% ~ 180%，恐慌時掉到 130% ~ 145%)
        base_total_ratio = 170.0 + (change_pct * 450) - (c_130 / 35.0)
        base_total_ratio = max(124.0, min(198.0, base_total_ratio))
        total_margin_ratio.append(round(base_total_ratio, 1))
        
        current_date += timedelta(days=1)
        trade_day_count += 1
        
    return {
        "dates": dates,
        "taiex": taiex,
        "margin_counts": {
            "130": maint_130,
            "140": maint_140,
            "150": maint_150,
            "160": maint_160
        },
        "breadth": {
            "ma20": breadth_20ma,
            "ma60": breadth_60ma
        },
        "total_margin_ratio": total_margin_ratio
    }

if __name__ == "__main__":
    data = generate_mock_historical_data(days=650)
    output_file = "c:/Users/Ernesto/Documents/工作區/市場廣度觀察/data.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Data successfully generated to {output_file}")
