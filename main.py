import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=1800)  # 快取 30 分鐘，避免重複刷網頁轟炸 API
def get_packaged_stock_data(base_date):
    """
    優化策略：採取「單次大禮包」抓取。
    直接一口氣抓取過去 12 天的區間資料，將請求次數降到最低，免除被 API 限制的困境。
    """
    # 計算回溯天數的起迄區間
    start_dt = base_date - timedelta(days=12)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = base_date.strftime("%Y-%m-%d")
    
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&start_date={start_str}&end_date={end_str}"
    price_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date={start_str}&end_date={end_str}"
    
    try:
        # 1. 抓取全區間法人資料
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200 or not resp.json().get("data"):
            return [], []
        df_raw = pd.DataFrame(resp.json()["data"])
        if df_raw.empty:
            return [], []
            
        # 2. 抓取全區間價格資料
        resp_p = requests.get(price_url, timeout=15)
        if resp_p.status_code != 200 or not resp_p.json().get("data"):
            return [], []
        df_price_raw = pd.DataFrame(resp_p.json()["data"])
        if df_price_raw.empty:
            return [], []
            
        # 找出這段區間內所有出現過的實際交易日期（由新到舊排序）
        all_dates = sorted(df_raw['date'].unique(), reverse=True)
        
        # 我們只需要最新的 5 個實際交易日
        trading_dates = all_dates[:5]
        if not trading_dates:
            return [], []
            
        packaged_dfs = []
        actual_dates_found = []
        
        # 在記憶體內進行拆解與合併
        for t_date in trading_dates:
            df_day = df_raw[df_raw['date'] == t_date]
            df_f = df_day[df_day['name'] == 'Foreign_Investor'].copy()
            df_s = df_day[df_day['name'] == 'Investment_Trust'].copy()
            
            if df_f.empty and df_s.empty:
                continue
                
            # 轉換為張數 (股數 / 1000)
            df_f['外資買進(張)'] = (df_f['buy'] / 1000).round(1)
            df_f['外資賣出(張)'] = (df_f['sell'] / 1000).round(1)
            df_f['外資買賣超(張)'] = (df_f['buy_sell'] / 1000).round(1)
            
            df_s['投信買進(張)'] = (df_s['buy'] / 1000).round(1)
            df_s['投信賣出(張)'] = (df_s['sell'] / 1000).round(1)
            df_s['投信買賣超(張)'] = (df_s['buy_sell'] / 1000).round(1)
            
            m1 = pd.merge(df_f[['stock_id', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)']], 
                          df_s[['stock_id', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)']], 
                          on='stock_id', how='outer').fillna(0)
            
            # 篩選當日價格
            df_p_day = df_price_raw[df_price_raw['date'] == t_date].drop_duplicates(subset=['stock_id'], keep='last').copy()
            if df_p_day.empty:
                continue
                
            df_p_day['漲跌'] = df_p_day['change'].apply(lambda x: f"▲ {x}" if x > 0 else (f"▼ {abs(x)}" if x < 0 else "0.00"))
            
            # 合併價格與籌碼
            final_df = pd.merge(m1, df_p_day[['stock_id', 'stock_name', 'close', '漲跌']], on='stock_id', how='inner')
            
            # 補齊前端介面需要的延伸欄位
            final_df['外資持股張數'] = 0
            final_df['外資持股比率(%)'] = 0.0
            final_df['投信持股張數'] = 0
            final_df['投信持股比率(%)'] = 0.0
