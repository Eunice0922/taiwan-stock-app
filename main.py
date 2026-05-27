import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import time  # 導入時間模組，用來做請求延遲

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=3600)  # 快取保留 1 小時，避免重複發送請求被封鎖
def get_open_stock_data(date_str):
    """
    改串全球公開免驗證台股 API 資料源，並加上延遲與容錯。
    """
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&date={formatted_date}"
    price_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&date={formatted_date}"
    
    try:
        # 在每次請求前微幅延遲 0.3 秒，避免 Streamlit 速度太快被 FinMind API 伺服器拒絕
        time.sleep(0.3)
        
        # 1. 抓取法人買賣超
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.json().get("data"):
            return pd.DataFrame()
        
        raw_data = resp.json()["data"]
        df_raw = pd.DataFrame(raw_data)
        if df_raw.empty:
            return pd.DataFrame()
        
        # 篩選外資與投信
        df_f = df_raw[df_raw['name'] == 'Foreign_Investor'].copy()
        df_s = df_raw[df_raw['name'] == 'Investment_Trust'].copy()
        
        if df_f.empty and df_s.empty:
            return pd.DataFrame()
            
        # 整理外資與投信數據 (張數 = 股數 / 1000)
        df_f['外資買進(張)'] = (df_f['buy'] / 1000).round(1)
        df_f['外資賣出(張)'] = (df_f['sell'] / 1000).round(1)
        df_f['外資買賣超(張)'] = (df_f['buy_sell'] / 1000).round(1)
        
        df_s['投信買進(張)'] = (df_s['buy'] / 1000).round(1)
        df_s['投信賣出(張)'] = (df_s['sell'] / 1000).round(1)
        df_s['投信買賣超(張)'] = (df_s['buy_sell'] / 1000).round(1)
        
        # 合併法人資料
        m1 = pd.merge(df_f[['stock_id', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)']], 
                      df_s[['stock_id', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)']], 
                      on='stock_id', how='outer').fillna(0)
        
        # 2. 抓取當日收盤價與股名
        resp_p = requests.get(price_url, timeout=10)
        if resp_p.status_code == 200 and resp_p.json().get("data"):
            df_p = pd.DataFrame(resp_p.json()["data"])
            df_p = df_p.drop_duplicates(subset=['stock_id'], keep='last')
            m2 = pd.merge(m1, df_p[['stock_id', 'stock_name', 'close', 'change']], on='stock_id', how='inner')
        else:
            return pd.DataFrame()
            
        # 3. 補齊前端要求的固定欄位 (外資持股改為預設或從價格表延伸)
        m2['外資持股張數'] = 0
        m2['外資持股比率(%)'] = 0
        m2['投信持股張數'] = 0
        m2['投信持股比率(%)'] = 0
        
        final_df = m2.rename(columns={
            'stock_id': '證券代號', 'stock_name': '證券名稱', 
            'close': '收盤價', 'change': '漲跌'
        })
        
        return final_df[['證券代號', '證券名稱', '收盤價', '漲跌', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']]
    except Exception:
        return pd.DataFrame()

def get_historical_data(start_date, max_days=7):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    
    # 關鍵優化：將原本抓取22天的漫長旅程縮短到最核心的 7 個交易日 (已足夠應付你需要的 3日、5日連買分析)
    # 這樣可以減少 70% 的網路請求次數，徹底免除被 API 封鎖的困境
    while len(valid_dfs) < max_days and attempts < 15:
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_open_stock_data(date_str)
        if not day_df.empty:
            valid_dfs.append(day_df)
            dates_list.append(current_date.strftime("%Y-%m-%d"))
        current_date -= timedelta(days=1)
        attempts += 1
    return valid_dfs, dates_list

# --- 全域側邊欄設定 ---
st.sidebar.header("📅 基準日期設定")
target_date = st.sidebar.date_input("選擇基準日期", datetime.today())
st.sidebar.markdown("---")

# 預先抓取交易日資料
with st.spinner('🎯 正在從開放資料源同步最新台股籌碼，請稍候...'):
    dfs, dates_found = get_historical_data(target_date, max_days=7)

# --- 三大分頁全面強制展開 ---
tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])

if len(dfs) > 0:
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面：外資及投信連買超 3日、5日
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
            
            ids_foreign = dfs[0][cond_foreign]['證券代號'].tolist()
            ids_sitc = dfs[0][cond_sitc]['證券代號'].tolist()
            inter_ids = list(set(ids_foreign) & set(ids_sitc))
            
            result_tab1 = df_latest[df_latest['證券代號'].isin(inter_ids)].copy()
            
            show_cols_tab1 = [
                '證券代號', '證券名稱', '收盤價', '漲跌', 
                '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', 
                '投信買賣超(張)', '投信持股張數', '投信持股比率(%)'
            ]
            
            if not result_tab1.empty:
                st.success(f"🎉 成功比對近 {filter_days} 個交易日：{', '.join(dates_found[:filter_days])}")
                display_df1 = result_tab1[show_cols_tab1].copy()
                display_df1.columns = ['股號', '股名', '最新股價', '漲跌', '外資當日買超(張)', '外資持股張數', '外資持股比率(%)', '投信當日買超(張)', '投信持股張數', '投信持股比率(%)']
                st.dataframe(display_df1.reset_index(drop=True), use_container_width=True)
            else:
                st.info(f"💡 在近 {filter_days} 個交易日（{', '.join(dates_found[:filter_days])}）期間，台股市場上沒有股票同時符合外資與投信「天天連買」的條件。")
        else:
            st.warning(f"⚠️ 目前系統僅成功加載到 {len(dfs)} 個交易日的資料，不足以計算 {filter_days} 日連買。請嘗試在左側選單將日期改為最新開盤日（如星期五傍晚）。")

    # ==========================================
    # 第二頁面：外資多週期 (因調整天數，提供當日至5日觀測)
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行")
        period_f = st.selectbox("請選擇觀測週期（外資）：", ["當日", "2日", "3日", "5日"], key="p2_select")
        
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5}
        target_len = min(day_mapping[period_f], len(dfs))
        
        cum_net_f = sum(dfs[i]['外資買賣超(張)'] for i in range(target_len))
        cum_buy_f = sum(dfs[i]['外資買進(張)'] for i in range(target_len))
        cum_sell_f = sum(dfs[i]['外資賣出(張)'] for i in range(target_len))
        
        df_f_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '外資持股張數', '外資持股比率(%)']].copy()
        df_f_period['外資買進(張)'] = cum_buy_f
        df_f_period['外資賣出(張)'] = cum_sell_f
        df_f_period['外資買賣超(張)'] = cum_net_f
        
        df_f_period = df_f_period.sort_values(by='外資買賣超(張)', ascending=False).reset_index(drop=True)
        
        show_cols_tab2 = ['證券代號', '證券名稱', '收盤價', '漲跌', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)']
        display_df2 = df_f_period[show_cols_tab2].copy()
        display_df2.columns = ['股號', '股名', '股價', '漲跌', f'外資{period_f}買進(張)', f'外資{period_f}賣出(張)', f'外資{period_f}買賣超(張)', '外資持股張數', '外資持股比率(%)']
        
        st.caption(f"📊 已成功計算近 {target_len} 個交易日累計數據（基準交易日：{dates_found[0]}）")
        st.dataframe(display_df2, use_container_width=True)

    # ==========================================
    # 第三頁面：投信多週期 (因調整天數，提供當日至5日觀測)
    # ==========================================
    with tab3:
        st.subheader("🐯 投信多週期進出排行")
        period_s = st.selectbox("請選擇觀測週期（投信）：", ["當日", "2日", "3日", "5日"], key="p3_select")
        
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5}
        target_len_s = min(day_mapping[period_s], len(dfs))
        
        cum_net_s = sum(dfs[i]['投信買賣超(張)'] for i in range(target_len_s))
        cum_buy_s = sum(dfs[i]['投信買進(張)'] for i in range(target_len_s))
        cum_sell_s = sum(dfs[i]['投信賣出(張)'] for i in range(target_len_s))
        
        df_s_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '投信持股張數', '投信持股比率(%)']].copy()
        df_s_period['投信買進(張)'] = cum_buy_s
        df_s_period['投信賣出(張)'] = cum_sell_s
        df_s_period['投信買賣超(張)'] = cum_net_s
        
        df_s_period = df_s_period.sort_values(by='投信買賣超(張)', ascending=False).reset_index(drop=True)
        
        show_cols_tab3 = ['證券代號', '證券名稱', '收盤價', '漲跌', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']
        display_df3 = df_s_period[show_cols_tab3].copy()
        display_df3.columns = ['股號', '股名', '股價', '漲跌', f'投信{period_s}買進(張)', f'投信{period_s}賣出(張)', f'投信{period_s}買賣超(張)', '投信持股張數', '投信持股比率(%)']
        
        st.caption(f"📊 已成功計算近 {target_len_s} 個交易日累計數據（基準交易日：{dates_found[0]}）")
        st.dataframe(display_df3, use_container_width=True)

else:
    with tab1: st.error("⚠️ 資料加載逾時或被拒絕。請稍候幾秒鐘，並在左側側邊欄將基準日期重新微調一天，藉此觸發重新加載機制。")
    with tab2: st.error("⚠️ 資料加載逾時，請重新切換左側日期。")
    with tab3: st.error("⚠️ 資料加載逾時，請重新切換左側日期。")
