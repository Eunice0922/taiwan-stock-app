import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=3600)
def get_twse_data(date_str):
    """從證交所抓取當日所有股票的法人買賣超與持股資料"""
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86KJ7?date={date_str}&selectType=ALL&response=json"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get("stat") == "OK":
            cols = data["fields"]
            rows = data["data"]
            df = pd.DataFrame(rows, columns=cols)
            
            df['證券代號'] = df['證券代號'].str.strip()
            df['證券名稱'] = df['證券名稱'].str.strip()
            
            # 轉換數值欄位（處理千分位逗號）
            df['收盤價'] = pd.to_numeric(df['收盤價'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            
            # 買進賣出股數轉張數
            df['外資買進(張)'] = (pd.to_numeric(df['外資買進股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            df['外資賣出(張)'] = (pd.to_numeric(df['外資賣出股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            df['外資買賣超(張)'] = (pd.to_numeric(df['外資買賣超股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            
            df['投信買進(張)'] = (pd.to_numeric(df['投信買進股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            df['投信賣出(張)'] = (pd.to_numeric(df['投信賣出股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            df['投信買賣超(張)'] = (pd.to_numeric(df['投信買賣超股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(1)
            
            # 持股張數與比率
            df['外資持股張數'] = (pd.to_numeric(df['外資持股股數'].astype(str).str.replace(',', ''), errors='coerce').fillna(0) / 1000).round(0)
            df['外資持股比率(%)'] = pd.to_numeric(df['外資持股比率'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
            
            # 備註：官方無當日投信持股總量，以0或相對應資料代入，此處保留欄位給前端顯示
            df['投信持股張數'] = 0 
            df['投信持股比率(%)'] = 0
            
            # 漲跌欄位處理
            df['漲跌'] = df['漲跌'].astype(str)
            
            return df[['證券代號', '證券名稱', '收盤價', '漲跌', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']]
        else:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# 根據天數取得歷史交易日資料
def get_historical_data(start_date, max_days=30):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    # 30天數據因包含週末，最多往回找 50 天
    while len(valid_dfs) < max_days and attempts < max_days * 2:
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_twse_data(date_str)
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

# 預先抓取最多 22 個交易日（約一個月）的資料
with st.spinner('正在從證交所載入歷史籌碼數據...'):
    # 22個交易日代表一個月
    dfs, dates_found = get_historical_data(target_date, max_days=22)

if len(dfs) > 0:
    # --- 分頁系統設計 ---
    tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])
    
    # 最新一天的基準資料
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面：外資及投信連買超 3日、5日
    # ==========================================
    with tab1:
        st.subheader("🔥 外資與投信聯手連買篩選")
        filter_days = st.radio("請選擇連續買超天數：", [3, 5], horizontal=True)
        
        if len(dfs) >= filter_days:
            # 計算連買
            cond_foreign = True
            cond_sitc = True
            for i in range(filter_days):
                cond_foreign &= (dfs[i]['外資買賣超(張)'] > 0)
                cond_sitc &= (dfs[i]['投信買賣超(張)'] > 0)
            
            # 連買代號清單
            ids_foreign = dfs[0][cond_foreign]['證券代號'].tolist()
            ids_sitc = dfs[0][cond_sitc]['證券代號'].tolist()
            
            # 取交集（外資與投信都連買）
            inter_ids = list(set(ids_foreign) & set(ids_sitc))
            
            # 篩選最新一天的資料來呈現
            result_tab1 = df_latest[df_latest['證券代號'].isin(inter_ids)].copy()
            
            # 計算連買期間的累積買超張數
            f_sum = sum(dfs[i]['外資買賣超(張)'] for i in range(filter_days))
            s_sum = sum(dfs[i]['投信買賣超(張)'] for i in range(filter_days))
            
            # 美化呈現表格
            show_cols_tab1 = [
                '證券代號', '證券名稱', '收盤價', '漲跌', 
                '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', 
                '投信買賣超(張)', '投信持股張數', '投信持股比率(%)'
            ]
            
            if not result_tab1.empty:
                st.success(f"🎉 成功找出 {len(result_tab1)} 檔外資與投信同步連買 {filter_days} 日的黃金股！")
                display_df1 = result_tab1[show_cols_tab1].copy()
                display_df1.columns = ['股號', '股名', '股價', '漲跌', '外資當日買超(張)', '外資持股張數', '外資持股比率(%)', '投信當日買超(張)', '投信持股張數', '投信持股比率(%)']
                st.dataframe(display_df1.reset_index(drop=True), use_container_width=True)
            else:
                st.info(f"💡 目前連續 {filter_days} 日無兩大法共同連買的股票。")
        else:
            st.warning(f"⚠️ 歷史交易日資料不足以計算 {filter_days} 日連買。")

    # ==========================================
    # 第二頁面：外資進出(當日、2日、3日、5日、10日、1個月)
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行")
        period_f = st.selectbox("請選擇觀測週期（外資）：", ["當日", "2日", "3日", "5日", "10日", "1個月（22日）"])
        
        # 對應要加總的天數
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5, "10日": 10, "1個月（22日）": 22}
        target_len = min(day_mapping[period_f], len(dfs))
        
        # 計算週期內的累計買賣超
        cum_net_f = sum(dfs[i]['外資買賣超(張)'] for i in range(target_len))
        cum_buy_f = sum(dfs[i]['外資買進(張)'] for i in range(target_len))
        cum_sell_f = sum(dfs[i]['外資賣出(張)'] for i in range(target_len))
        
        df_f_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '外資持股張數', '外資持股比率(%)']].copy()
        df_f_period['外資買進(張)'] = cum_buy_f
        df_f_period['外資賣出(張)'] = cum_sell_f
        df_f_period['外資買賣超(張)'] = cum_net_f
        
        # 依買賣超排序
        df_f_period = df_f_period.sort_values(by='外資買賣超(張)', ascending=False).reset_index(drop=True)
        
        show_cols_tab2 = ['證券代號', '證券名稱', '收盤價', '漲跌', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)']
        display_df2 = df_f_period[show_cols_tab2].copy()
        display_df2.columns = ['股號', '股名', '股價', '漲跌', f'外資{period_f}買進(張)', f'外資{period_f}賣出(張)', f'外資{period_f}買賣超(張)', '外資持股張數', '外資持股比率(%)']
        
        st.caption(f"📊 已計算近 {target_len} 個交易日累計數據（基準日：{dates_found[0]}）")
        st.dataframe(display_df2, use_container_width=True)

    # ==========================================
    # 第三頁面：投信進出(當日、2日、3日、5日、10日、1個月)
    # ==========================================
    with tab3:
        st.subheader("🐯 投信多週期進出排行")
        period_s = st.selectbox("請選擇觀測週期（投信）：", ["當日", "2日", "3日", "5日", "10日", "1個月（22日）"])
        
        target_len_s = min(day_mapping[period_s], len(dfs))
        
        # 計算週期內的累計買賣超
        cum_net_s = sum(dfs[i]['投信買賣超(張)'] for i in range(target_len_s))
        cum_buy_s = sum(dfs[i]['投信買進(張)'] for i in range(target_len_s))
        cum_sell_s = sum(dfs[i]['投信賣出(張)'] for i in range(target_len_s))
        
        df_s_period = df_latest[['證券代號', '證券名稱', '收盤價', '漲跌', '投信持股張數', '投信持股比率(%)']].copy()
        df_s_period['投信買進(張)'] = cum_buy_s
        df_s_period['投信賣出(張)'] = cum_sell_s
        df_s_period['投信買賣超(張)'] = cum_net_s
        
        # 依買賣超排序
        df_s_period = df_s_period.sort_values(by='投信買賣超(張)', ascending=False).reset_index(drop=True)
        
        show_cols_tab3 = ['證券代號', '證券名稱', '收盤價', '漲跌', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']
        display_df3 = df_s_period[show_cols_tab3].copy()
        display_df3.columns = ['股號', '股名', '股價', '漲跌', f'投信{period_s}買進(張)', f'投信{period_s}賣出(張)', f'投信{period_s}買賣超(張)', '投信持股張數', '投信持股比率(%)']
        
        st.caption(f"📊 已計算近 {target_len_s} 個交易日累計數據（基準日：{dates_found[0]}）")
        st.dataframe(display_df3, use_container_width=True)

else:
    st.warning("⚠️ 無法取得任何有效的交易日資料，請換個日期試試看。")
