import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=1800)  # 快取 30 分鐘，避免重複刷網頁轟炸 API
def get_packaged_stock_data(base_date):
    """
    終極優化：採取「單次大禮包」抓取策略！
    直接一口氣抓取過去 10 天的區間資料，將請求次數從 10 次降到 2 次，徹底免除被 API 封鎖的困境。
    """
    # 計算回溯 10 天的起迄區間
    start_dt = base_date - timedelta(days=12)
    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = base_date.strftime("%Y-%m-%d")
    
    # 建立區間請求 URL
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&start_date={start_str}&end_date={end_str}"
    price_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&start_date={start_str}&end_date={end_str}"
    
    try:
        # 1. 一口氣抓取全區間法人資料
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200 or not resp.json().get("data"):
            return [], []
        df_raw = pd.DataFrame(resp.json()["data"])
        if df_raw.empty:
            return [], []
            
        # 2. 一口氣抓取全區間價格資料
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
        
        # 在記憶體內進行高效拆解，完全不消耗網路流量
        for t_date in trading_dates:
            # 篩選當日法人
            df_day = df_raw[df_raw['date'] == t_date]
            df_f = df_day[df_day['name'] == 'Foreign_Investor'].copy()
            df_s = df_day[df_day['name'] == 'Investment_Trust'].copy()
            
            if df_f.empty and df_s.empty:
                continue
                
            # 轉換為張數
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
            
            # 合併
            final_df = pd.merge(m1, df_p_day[['stock_id', 'stock_name', 'close', '漲跌']], on='stock_id', how='inner')
            
            # 補齊虛擬延伸欄位
            final_df['外資持股張數'] = 0
            final_df['外資持股比率(%)'] = 0.0
            final_df['投信持股張數'] = 0
            final_df['投信持股比率(%)'] = 0.0
            
            final_df = final_df.rename(columns={'stock_id': '證券代號', 'stock_name': '證券名稱', 'close': '收盤價'})
            
            packaged_dfs.append(final_df)
            actual_dates_found.append(t_date)
            
        return packaged_dfs, actual_dates_found
    except Exception:
        return [], []

# --- 全域側邊欄設定 ---
st.sidebar.header("📅 基準日期設定")
target_date = st.sidebar.date_input("選擇基準日期", datetime.today())
st.sidebar.markdown("---")

with st.spinner('🎯 正在打包下載台股歷史籌碼大禮包，請稍候...'):
    dfs, dates_found = get_packaged_stock_data(target_date)

# --- 三大分頁展開 ---
tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])

if len(dfs) > 0:
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面：雙法人連買
    # ==========================================
    with tab1:
        st.subheader("🔥 外資與投信聯手連買篩選")
        filter_days = st.radio("請選擇連續買超天數：", [3, 5], horizontal=True, key="p1_days")
        
        if len(dfs) >= filter_days:
            cond_foreign = True
            cond_sitc = True
            for i in range(filter_days):
                cond_foreign &= (dfs[i]['外資買賣超(張)'] > 0)
                cond_sitc &= (dfs[i]['投信買賣超(張)'] > 0)
            
            inter_ids = list(set(dfs[0][cond_foreign]['證券代號'].tolist()) & set(dfs[0][cond_sitc]['證券代號'].tolist()))
            result_tab1 = df_latest[df_latest['證券代號'].isin(inter_ids)].copy()
            
            if not result_tab1.empty:
                st.success(f"🎉 成功比對！近 {filter_days} 個交易日（{', '.join(dates_found[:filter_days])}）法人聯手連買股：")
                show_cols_tab1 = ['證券代號', '證券名稱', '收盤價', '漲跌', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']
                display_df1 = result_tab1[show_cols_tab1].copy()
                display_df1.columns = ['股號', '股名', '最新股價', '漲跌', '外資當日買超(張)', '外資持股張數', '外資持股比率(%)', '投信當日買超(張)', '投信持股張數', '投信持股比率(%)']
                st.dataframe(display_df1.reset_index(drop=True), use_container_width=True)
            else:
                st.info(f"💡 近 {filter_days} 個交易日（{', '.join(dates_found[:filter_days])}）期間，全市場沒有股票符合外資與投信「同時天天連買」的條件。")
        else:
            st.warning(f"⚠️ 該區間內載入的有效開盤日僅有 {len(dfs)} 天，不足以計算 {filter_days} 日連買。請將基準日調整到最新開盤日。")

    # ==========================================
    # 第二頁面：外資排行
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行 (真實張數)")
        period_f = st.selectbox("請選擇觀測週期（外資）：",
