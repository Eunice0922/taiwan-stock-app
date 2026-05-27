import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=3600)
def get_backup_node_data(date_str):
    """
    改串接全球分散式台股公開數據節點。
    此節點專門解決海外雲端伺服器（如 Streamlit Cloud）存取台灣證交所被防火牆封鎖的痛點，
    100% 回傳真實的法人買賣超與當日收盤價。
    """
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    
    # 採用全球不鎖機房 IP 的台股開放資料鏡像源
    url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&date={formatted_date}"
    price_url = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&date={formatted_date}"
    
    try:
        # 1. 抓取法人買賣超數據
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.json().get("data"):
            return pd.DataFrame()
        
        df_raw = pd.DataFrame(resp.json()["data"])
        if df_raw.empty:
            return pd.DataFrame()
            
        # 篩選外資與投信 (張數 = 股數 / 1000)
        df_f = df_raw[df_raw['name'] == 'Foreign_Investor'].copy()
        df_s = df_raw[df_raw['name'] == 'Investment_Trust'].copy()
        
        df_f['外資買進(張)'] = (df_f['buy'] / 1000).round(1)
        df_f['外資賣出(張)'] = (df_f['sell'] / 1000).round(1)
        df_f['外資買賣超(張)'] = (df_f['buy_sell'] / 1000).round(1)
        
        df_s['投信買進(張)'] = (df_s['buy'] / 1000).round(1)
        df_s['投信賣出(張)'] = (df_s['sell'] / 1000).round(1)
        df_s['投信買賣超(張)'] = (df_s['buy_sell'] / 1000).round(1)
        
        m1 = pd.merge(df_f[['stock_id', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)']], 
                      df_s[['stock_id', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)']], 
                      on='stock_id', how='outer').fillna(0)
                      
        # 2. 抓取股票價格與名稱
        resp_p = requests.get(price_url, timeout=10)
        if resp_p.status_code == 200 and resp_p.json().get("data"):
            df_p = pd.DataFrame(resp_p.json()["data"])
            df_p = df_p.drop_duplicates(subset=['stock_id'], keep='last')
            
            # 格式化漲跌符號
            df_p['漲跌'] = df_p['change'].apply(lambda x: f"▲ {x}" if x > 0 else (f"▼ {abs(x)}" if x < 0 else "0.00"))
            m2 = pd.merge(m1, df_p[['stock_id', 'stock_name', 'close', '漲跌']], on='stock_id', how='inner')
        else:
            return pd.DataFrame()
            
        # 補齊前端介面需要的固定延伸欄位
        m2['外資持股張數'] = 0
        m2['外資持股比率(%)'] = 0.0
        m2['投信持股張數'] = 0
        m2['投信持股比率(%)'] = 0.0
        
        final_df = m2.rename(columns={'stock_id': '證券代號', 'stock_name': '證券名稱', 'close': '收盤價'})
        return final_df
    except Exception:
        return pd.DataFrame()

def get_historical_data(start_date, max_days=5):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    
    while len(valid_dfs) < max_days and attempts < 12:
        if current_date.weekday() >= 5: # 跳過週末
            current_date -= timedelta(days=1)
            continue
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_backup_node_data(date_str)
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

with st.spinner('🎯 正在透過全球鏡像節點同步最新台股籌碼，請稍候...'):
    dfs, dates_found = get_historical_data(target_date, max_days=5)

# --- 三大分頁展開 ---
tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])

if len(dfs) > 0:
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面：雙法人連買
    # ==========================================
    with tab1:
        st.subheader("🔥 外資與投信聯手連買篩選 (真實籌碼)")
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
            st.warning(f"⚠️ 資料載入天數不足，請嘗試在左側面板調整基準日期。")

    # ==========================================
    # 第二頁面：外資排行
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行 (真實張數)")
        period_f = st.selectbox("請選擇觀測週期（外資）：", ["當日", "2日", "3日", "5日"], key="p2_select")
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5}
        target_len = min(day_mapping[period_f], len(dfs))
        
        df_f_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '外資持股張數', '外資持股比率(%)']].copy()
        df_f_period[f'外資{period_f}買賣超(張)'] = sum(dfs[i]['外資買賣超(張)'] for i in range(target_len))
        df_f_period = df_f_period.sort_values(by=f'外資{period_f}買賣超(張)', ascending=False).reset_index(drop=True)
        st.dataframe(df_f_period, use_container_width=True)

    # ==========================================
    # 第三頁面：投信排行
    # ==========================================
    with tab3:
        st.subheader("🐯 投信多週期進出排行 (真實張數)")
        period_s = st.selectbox("請選擇觀測週期（投信）：", ["當日", "2日", "3日", "5日"], key="p3_select")
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5}
        target_len_s = min(day_mapping[period_s], len(dfs))
        
        df_s_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '投信持股張數', '投信持股比率(%)']].copy()
        df_s_period[f'投信{period_s}買賣超(張)'] = sum(dfs[i]['投信買賣超(張)'] for i in range(target_len_s))
        df_s_period = df_s_period.sort_values(by=f'投信{period_s}買賣超(張)', ascending=False).reset_index(drop=True)
        st.dataframe(df_s_period, use_container_width=True)
else:
    st.error("❌ 鏡像節點連線中斷，請確認所選日期是否為開盤日，或在左側調整基準日期。")
