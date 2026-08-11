/**
 * 台股市場廣度儀表板 - 耐看沉穩金融主題 (Eye-Friendly Light Theme app.js)
 * 特色功能：
 * 1. 專業級深沉低明度色彩系統 (降低飽和度與高光，長期看盤舒適不刺眼)
 * 2. 數據防呆驗證機制 (自動過濾未發布或殘缺日)
 * 3. 徹底消除門檻/類別切換時的 dataZoom 飄移 BUG (保持全圖精確鎖定對齊)
 * 4. 右側鎖定與最新交易日錨定縮放 (Right-Anchored Wheel Zoom)
 * 5. 一鍵「📍 移至最新」與快捷時間範圍 (近1M / 3M / 6M / 全部)
 * 6. 四圖全向同步連動
 */

document.addEventListener('DOMContentLoaded', async () => {
    const dates = [];
    const taiex = [];
    const margin_counts = { "130": [], "140": [], "150": [], "160": [] };
    const breadth = { ma20: [], ma60: [] };
    const total_margin_ratio = [];
    const twse_margin_ratio = [];
    const tpex_margin_ratio = [];

    // 全局維持唯一的縮放視角狀態，徹底解決切換門檻/類別時對齊飄移的 BUG
    let currentZoomStart = 0;
    let currentZoomEnd = 100;

    // 嘗試多種路徑讀取 CSV 數據
    const possiblePaths = [
        'data/daily_market_breadth.csv',
        'daily_market_breadth.csv'
    ];

    let csvText = null;

    for (const path of possiblePaths) {
        try {
            const cacheBuster = '?v=' + Date.now();
            const response = await fetch(path + cacheBuster);
            if (response.ok) {
                csvText = await response.text();
                break;
            }
        } catch (e) {
            // file:// 協定或 fetch 失敗時繼續下一個
        }
    }

    // 若 fetch 被瀏覽器安全限制 (例如直接雙擊 file:// index.html) 或沒找到檔案，使用內建備用數據
    if (!csvText && window.FALLBACK_CSV) {
        csvText = window.FALLBACK_CSV;
    }

    if (csvText) {
        const lines = csvText.trim().split('\n');
        for (let i = 1; i < lines.length; i++) {
            const cols = lines[i].split(',').map(s => s.trim());
            if (cols.length >= 9) {
                const ratio = parseFloat(cols[8]) || 0;
                const pIndex = parseFloat(cols[1]) || 0;
                
                // 【防呆機制】：必須當日大盤 > 0 且 維持率大於 50% (代表融資資料已完整更新)
                if (pIndex > 0 && ratio >= 50.0) {
                    dates.push(cols[0]);
                    taiex.push(pIndex);
                    margin_counts["130"].push(parseInt(cols[2]) || 0);
                    margin_counts["140"].push(parseInt(cols[3]) || 0);
                    margin_counts["150"].push(parseInt(cols[4]) || 0);
                    margin_counts["160"].push(parseInt(cols[5]) || 0);
                    breadth.ma20.push(parseFloat(cols[6]) || 0);
                    breadth.ma60.push(parseFloat(cols[7]) || 0);
                    total_margin_ratio.push(ratio);
                    twse_margin_ratio.push(parseFloat(cols[9]) || (ratio * 0.81) || 0);
                    tpex_margin_ratio.push(parseFloat(cols[10]) || ratio || 0);
                } else {
                    console.warn(`[防呆過濾] 跳過數據不完整的交易日: ${cols[0]}`);
                }
            }
        }
    }

    if (dates.length === 0) {
        console.error('無可用數據！');
        return;
    }

    let currentThreshold = '130';
    let currentMarginType = 'all'; // 'all', 'twse', 'tpex'

    // 初始化 4 個 ECharts 實例 (使用白底 Light 模式)
    const domTaiex = document.getElementById('chartTaiex');
    const domMarginCount = document.getElementById('chartMarginCount');
    const domBreadth = document.getElementById('chartBreadth');
    const domTotalMargin = document.getElementById('chartTotalMargin');

    const chartTaiex = echarts.init(domTaiex, null);
    const chartMarginCount = echarts.init(domMarginCount, null);
    const chartBreadth = echarts.init(domBreadth, null);
    const chartTotalMargin = echarts.init(domTotalMargin, null);

    const commonGrid = {
        left: '55px',
        right: '40px',
        top: '15px',
        bottom: '25px',
        containLabel: false
    };

    const commonXAxis = {
        type: 'category',
        data: dates,
        boundaryGap: false,
        axisLine: { lineStyle: { color: '#CBD5E1' } },
        axisLabel: { show: false, color: '#64748B' },
        axisTick: { show: false },
        splitLine: { show: true, lineStyle: { color: '#F1F5F9', type: 'dashed' } }
    };

    // 通用同步縮放配置 (dataZoom)，白底樣式
    const getCommonDataZoom = (showSlider = false) => [
        {
            type: 'inside',
            xAxisIndex: [0],
            start: currentZoomStart,
            end: currentZoomEnd,
            zoomLock: false
        },
        {
            type: 'slider',
            xAxisIndex: [0],
            show: showSlider,
            start: currentZoomStart,
            end: currentZoomEnd,
            bottom: '2px',
            height: 18,
            borderColor: '#CBD5E1',
            fillerColor: 'rgba(37, 99, 235, 0.12)',
            handleStyle: { color: '#2563EB' },
            textStyle: { color: '#64748B' },
            brushSelect: false
        }
    ];

    const commonTooltip = {
        trigger: 'axis',
        axisPointer: { type: 'cross', label: { backgroundColor: '#2563EB' } },
        borderWidth: 1,
        borderColor: '#E2E8F0',
        backgroundColor: '#FFFFFF',
        textStyle: { color: '#0F172A', fontSize: 12 },
        extraCssText: 'box-shadow: 0 4px 16px rgba(15, 23, 42, 0.12); border-radius: 8px;'
    };

    // --- 子圖一：加權指數 TAIEX (採用沉穩深緋紅 #B91C1C) ---
    const optTaiex = {
        backgroundColor: 'transparent',
        grid: commonGrid,
        dataZoom: getCommonDataZoom(false),
        tooltip: commonTooltip,
        xAxis: commonXAxis,
        yAxis: {
            type: 'value',
            scale: true,
            axisLabel: { color: '#475569', formatter: (val) => val.toLocaleString() },
            splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } }
        },
        series: [{
            name: '加權指數 TAIEX',
            type: 'line',
            data: taiex,
            symbol: 'none',
            smooth: 0.1,
            lineStyle: { width: 1.8, color: '#B91C1C' },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(185, 28, 28, 0.08)' },
                    { offset: 1, color: 'rgba(185, 28, 28, 0.0)' }
                ])
            }
        }]
    };

    // --- 子圖二：維持率 < 門檻 家數 (採用沉穩皇家藍 / 暖赭 / 銹紅) ---
    function getMarginCountOption(threshold) {
        const counts = margin_counts[threshold] || [];
        return {
            backgroundColor: 'transparent',
            grid: commonGrid,
            dataZoom: getCommonDataZoom(false),
            tooltip: {
                ...commonTooltip,
                axisPointer: { type: 'shadow' }
            },
            xAxis: commonXAxis,
            yAxis: {
                type: 'value',
                axisLabel: { color: '#475569' },
                splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } }
            },
            series: [{
                name: `維持率 < ${threshold}% 家數`,
                type: 'bar',
                data: counts,
                itemStyle: {
                    color: (params) => {
                        const val = params.value;
                        if (val > 300) return '#C2410C'; // 沉穩銹紅
                        if (val > 150) return '#D97706'; // 暖赭琥珀
                        return '#2563EB'; // 皇家鋼鐵藍
                    }
                }
            }]
        };
    }

    // --- 子圖三：市場廣度 (% 站上 20MA / 60MA) ---
    const optBreadth = {
        backgroundColor: 'transparent',
        grid: commonGrid,
        dataZoom: getCommonDataZoom(false),
        tooltip: commonTooltip,
        xAxis: commonXAxis,
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            interval: 25,
            axisLabel: { color: '#475569', formatter: '{value}%' },
            splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } }
        },
        series: [
            {
                name: '20MA 站上比例',
                type: 'line',
                data: breadth.ma20,
                symbol: 'none',
                smooth: 0.1,
                lineStyle: { width: 1.8, color: '#2563EB' } // 沉穩皇家藍
            },
            {
                name: '60MA 站上比例',
                type: 'line',
                data: breadth.ma60,
                symbol: 'none',
                smooth: 0.1,
                lineStyle: { width: 1.8, color: '#4F46E5' } // 典雅靛藍紫
            }
        ]
    };

    // --- 子圖四：融資維持率 % (動態切換：全市場 / 上市 / 上櫃) ---
    function getTotalMarginOption(type) {
        let seriesData = total_margin_ratio;
        let seriesName = '全市場融資維持率 %';
        let lineColor = '#2563EB'; // 沉穩皇家藍

        if (type === 'twse') {
            seriesData = twse_margin_ratio;
            seriesName = '上市融資維持率 %';
            lineColor = '#B45309'; // 沉穩青古銅金
        } else if (type === 'tpex') {
            seriesData = tpex_margin_ratio;
            seriesName = '上櫃融資維持率 %';
            lineColor = '#047857'; // 深森林綠
        }

        return {
            backgroundColor: 'transparent',
            grid: {
                ...commonGrid,
                bottom: '35px' // 留出空間給底部滑桿 slider
            },
            dataZoom: getCommonDataZoom(true), // 顯示底部縮放滑桿
            tooltip: commonTooltip,
            xAxis: {
                ...commonXAxis,
                axisLabel: { show: true, color: '#64748B', margin: 8 }
            },
            yAxis: {
                type: 'value',
                scale: true,
                axisLabel: { color: '#475569', formatter: '{value}%' },
                splitLine: { lineStyle: { color: '#F1F5F9', type: 'dashed' } }
            },
            series: [{
                name: seriesName,
                type: 'line',
                data: seriesData,
                symbol: 'none',
                smooth: 0.2,
                lineStyle: { width: 2.0, color: lineColor },
                markLine: {
                    symbol: 'none',
                    data: [
                        { yAxis: 158, lineStyle: { color: '#B45309', type: 'dashed' }, label: { formatter: '158%', position: 'start', color: '#B45309' } },
                        { yAxis: 138, lineStyle: { color: '#B91C1C', type: 'dashed' }, label: { formatter: '138%', position: 'start', color: '#B91C1C' } }
                    ]
                }
            }]
        };
    }

    // Render 所有圖表
    chartTaiex.setOption(optTaiex);
    chartMarginCount.setOption(getMarginCountOption(currentThreshold));
    chartBreadth.setOption(optBreadth);
    chartTotalMargin.setOption(getTotalMarginOption(currentMarginType));

    // 【核心同步縮放與游標連動】：將 4 個子圖表全面綁定
    echarts.connect([chartTaiex, chartMarginCount, chartBreadth, chartTotalMargin]);

    // 取得當前所選類型的維持率陣列
    const getCurrentMarginArray = () => {
        if (currentMarginType === 'twse') return twse_margin_ratio;
        if (currentMarginType === 'tpex') return tpex_margin_ratio;
        return total_margin_ratio;
    };

    // 數據即時連動頭部 Header 與狀態欄數值顯示
    const updateHeaderValues = (dataIndex) => {
        const idx = (dataIndex !== undefined && dataIndex >= 0) ? dataIndex : dates.length - 1;
        document.getElementById('valTaiex').textContent = taiex[idx] ? taiex[idx].toLocaleString() : '--';
        document.getElementById('valMarginCount').textContent = `${margin_counts[currentThreshold][idx] || 0} 檔`;
        document.getElementById('valMa20').textContent = `${breadth.ma20[idx] || 0}%`;
        document.getElementById('valMa60').textContent = `${breadth.ma60[idx] || 0}%`;
        
        const targetArray = getCurrentMarginArray();
        document.getElementById('valTotalMargin').textContent = `${targetArray[idx] || 0}%`;

        // 箭頭處：最新數據交易日與狀態條連動更新 (獨立單行膠囊標籤，絕不折行)
        const elDate = document.getElementById('lblLatestDate');
        const elSummary = document.getElementById('lblDataSummary');
        if (elDate) elDate.textContent = dates[idx] || '-----';
        if (elSummary) {
            const curTaiex = taiex[idx] ? taiex[idx].toLocaleString() : '--';
            const curCount = margin_counts[currentThreshold][idx] !== undefined ? `${margin_counts[currentThreshold][idx]} 檔` : '-- 檔';
            const curMa20 = breadth.ma20[idx] !== undefined ? `${breadth.ma20[idx]}%` : '--%';
            const curMa60 = breadth.ma60[idx] !== undefined ? `${breadth.ma60[idx]}%` : '--%';
            const curTwse = twse_margin_ratio[idx] !== undefined ? `${twse_margin_ratio[idx]}%` : '--%';
            const curTpex = tpex_margin_ratio[idx] !== undefined ? `${tpex_margin_ratio[idx]}%` : '--%';
            
            elSummary.innerHTML = `
                <span class="m-pill">加權指數 <strong>${curTaiex}</strong></span>
                <span class="m-pill">&lt;${currentThreshold}% <strong class="c-orange">${curCount}</strong></span>
                <span class="m-pill">20MA <strong class="c-blue">${curMa20}</strong></span>
                <span class="m-pill">60MA <strong class="c-purple">${curMa60}</strong></span>
                <span class="m-pill">上市 <strong class="c-amber">${curTwse}</strong></span>
                <span class="m-pill">上櫃 <strong class="c-green">${curTpex}</strong></span>
            `.trim();
        }
    };

    updateHeaderValues();

    chartTaiex.on('updateAxisPointer', (event) => {
        const dataInfo = event.dataInfo;
        if (dataInfo && dataInfo.dataIndex !== undefined) {
            updateHeaderValues(dataInfo.dataIndex);
        }
    });

    // 🎯【全圖無縫同步對齊與右側錨定】
    let isProgrammaticZoom = false;
    const allCharts = [chartTaiex, chartMarginCount, chartBreadth, chartTotalMargin];

    const syncZoomAcrossAllCharts = (startPercent, endPercent = 100) => {
        if (isProgrammaticZoom) return;
        isProgrammaticZoom = true;

        currentZoomStart = startPercent;
        currentZoomEnd = endPercent;

        const zoomObj = {
            dataZoom: [
                { start: currentZoomStart, end: currentZoomEnd },
                { start: currentZoomStart, end: currentZoomEnd }
            ]
        };

        allCharts.forEach(c => c.setOption(zoomObj));
        isProgrammaticZoom = false;
        updateHeaderValues();
    };

    // 監聽 4 圖的 datazoom 事件，隨時同步全局縮放狀態
    allCharts.forEach(chart => {
        chart.on('datazoom', (e) => {
            if (isProgrammaticZoom) return;
            let start = currentZoomStart;
            let end = currentZoomEnd;

            if (e.batch && e.batch[0]) {
                start = e.batch[0].start;
                end = e.batch[0].end !== undefined ? e.batch[0].end : 100;
            } else if (e.start !== undefined) {
                start = e.start;
                end = e.end !== undefined ? e.end : 100;
            }
            
            currentZoomStart = start;
            currentZoomEnd = end;
            syncZoomAcrossAllCharts(currentZoomStart, currentZoomEnd);
        });
    });

    // 🎯【快捷時間範圍與「📍 移至最新」按鈕控制】
    const zoomPresetGroup = document.getElementById('zoomPresetGroup');
    if (zoomPresetGroup) {
        zoomPresetGroup.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-zoom');
            if (!btn) return;

            document.querySelectorAll('.btn-zoom').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            const range = btn.dataset.range;
            const totalLen = dates.length;
            let startPct = 0;

            if (range === '1m') {
                startPct = Math.max(0, ((totalLen - 22) / totalLen) * 100);
            } else if (range === '3m') {
                startPct = Math.max(0, ((totalLen - 65) / totalLen) * 100);
            } else if (range === '6m') {
                startPct = Math.max(0, ((totalLen - 130) / totalLen) * 100);
            } else if (range === 'all') {
                startPct = 0;
            }

            syncZoomAcrossAllCharts(startPct, 100);
        });

        // 📍「一鍵移至最新」按鈕
        const btnResetLatest = document.getElementById('btnResetLatest');
        if (btnResetLatest) {
            btnResetLatest.addEventListener('click', () => {
                syncZoomAcrossAllCharts(Math.max(0, currentZoomStart), 100);
                updateHeaderValues(dates.length - 1);
            });
        }
    }

    // 門檻選擇器切換 (130 / 140 / 150 / 160) - 【已修復縮放後切換維持對齊 BUG】
    const selectorContainer = document.getElementById('thresholdSelector');
    if (selectorContainer) {
        selectorContainer.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-threshold');
            if (!btn) return;

            document.querySelectorAll('.btn-threshold').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            currentThreshold = btn.dataset.threshold;
            document.getElementById('titleMarginCount').textContent = `融資維持率 < ${currentThreshold}% 家數`;
            
            // 重繪子圖二並套用當前的全局縮放，絕不飄移重置
            chartMarginCount.setOption(getMarginCountOption(currentThreshold));
            syncZoomAcrossAllCharts(currentZoomStart, currentZoomEnd);
        });
    }

    // 子圖四類型切換按鈕組 (全市場 / 上市 / 上櫃) - 【已修復縮放後切換維持對齊 BUG】
    const marginTypeBtnGroup = document.getElementById('btnGroupMarginType');
    if (marginTypeBtnGroup) {
        marginTypeBtnGroup.addEventListener('click', (e) => {
            const btn = e.target.closest('.btn-toggle');
            if (!btn) return;

            marginTypeBtnGroup.querySelectorAll('.btn-toggle').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');

            currentMarginType = btn.dataset.type;
            
            // 重繪子圖四並套用當前的全局縮放，絕不飄移重置
            chartTotalMargin.setOption(getTotalMarginOption(currentMarginType));
            syncZoomAcrossAllCharts(currentZoomStart, currentZoomEnd);
        });
    }

    window.addEventListener('resize', () => {
        chartTaiex.resize();
        chartMarginCount.resize();
        chartBreadth.resize();
        chartTotalMargin.resize();
    });
});
