import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
def get_twse_data(date_str):
    """從證交所最新 API 抓取當日所有股票的法人買賣超與持股資料"""
    # 測試另一種更直接的官方 API 格式
    url = f"https://www.twse.com.tw/exchangeReport/T86KJ7?response=json&date={date_str}&selectType=ALLBUT0999"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
        "Referer": "https://www.twse.com.tw/zh/page/trading/fund/T86KJ7.html"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        
        # 偵錯機制：如果不是 200，把錯誤代碼噴在畫面上
        if response.status_code != 200:
            st.error(f"🔍 證交所伺服器連線失敗，錯誤代碼 (Status Code): {response.status_code}")
            return pd.DataFrame()
            
        data = response.json()
        
        # 偵錯機制：如果證交所回應說沒有資料，印出原因
        if "stat" in data and data["stat"] != "OK":
            st.warning(f"ℹ️ 證交所提示：{data['stat']} (日期: {date_str})")
            return pd.DataFrame()
            
        if "data" in data and len(data["data"]) > 0:
            cols = data["fields"]
            rows = data["data"]
            df = pd.DataFrame(rows, columns=cols)
            
            df['證券代號'] = df['證券代號'].str.strip()
            df['證券名稱'] = df['證券名稱'].str.strip()
            
            def clean_num(val):
                val_str = str(val).replace(',', '').replace(' ', '').strip()
                return pd.to_numeric(val_str, errors='coerce')
            
            df['收盤價'] = clean_num(df['收盤價']).fillna(0)
            df['外資買進(張)'] = (clean_num(df['外資買進股數']).fillna(0) / 1000).round(1)
            df['外資賣出(張)'] = (clean_num(df['外資賣出股數']).fillna(0) / 1000).round(1)
            df['外資買賣超(張)'] = (clean_num(df['外資買賣超股數']).fillna(0) / 1000).round(1)
            df['投信買進(張)'] = (clean_num(df['投信買進股數']).fillna(0) / 1000).round(1)
            df['投信賣出(張)'] = (clean_num(df['投信賣出股數']).fillna(0) / 1000).round(1)
            df['投信買賣超(張)'] = (clean_num(df['投信買賣超股數']).fillna(0) / 1000).round(1)
            df['外資持股張數'] = (clean_num(df['外資持股股數']).fillna(0) / 1000).round(0)
            df['外資持股比率(%)'] = clean_num(df['外資持股比率']).fillna(0)
            df['投信持股張數'] = 0 
            df['投信持股比率(%)'] = 0
            df['漲跌'] = df['漲跌'].astype(str).str.replace(' ', '')
            
            return df[['證券代號', '證券名稱', '收盤價', '漲跌', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '外資持股張數', '外資持股比率(%)', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)', '投信持股張數', '投信持股比率(%)']]
        
        return pd.DataFrame()
    except Exception as e:
        st.error(f"💥 程式執行發生未知錯誤: {str(e)}")
        return pd.DataFrame()

# 根據天數取得歷史交易日資料
def get_historical_data(start_date, max_days=22):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    
    while len(valid_dfs) < max_days and attempts < 45:
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
with st.spinner('🎯 正在從台灣證交所同步最新數據中，請稍候...'):
    dfs, dates_found = get_historical_data(target_date, max_days=22)

# 無論有沒有成功抓到全部資料，直接強制渲染出三個分頁（解決分頁不顯示的問題）
tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])

if len(dfs) > 0:
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面
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
                st.info(f"💡 在 {', '.join(dates_found[:filter_days])} 期間，市場上沒有股票符合雙法人同時連買的條件。")
        else:
            st.warning(f"⚠️ 目前獲取的交易日數量（{len(dfs)}天）不足以計算 {filter_days} 日連買。")

    # ==========================================
    # 第二頁面
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行")
        period_f = st.selectbox("請選擇觀測週期（外資）：", ["當日", "2日", "3日", "5日", "10日", "1個月（22日）"], key="p2_select")
        
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5, "10日": 10, "1個月（22日）": 22}
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
    # 第三頁面
    # ==========================================
    with tab3:
        st.subheader("🐯 投信多週期進出排行")
        period_s = st.selectbox("請選擇觀測週期（投信）：", ["當日", "2日", "3日", "5日", "10日", "1個月（22日）"], key="p3_select")
        
        day_mapping = {"當日": 1, "2日": 2, "3日": 3, "5日": 5, "10日": 10, "1個月（22日）": 22}
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
    with tab1: st.error("❌ 目前無法取得有效的歷史交易日資料，請查看上方具體的錯誤訊息。")
    with tab2: st.error("❌ 目前無法取得有效的歷史交易日資料，請查看上方具體的錯誤訊息。")
    with tab3: st.error("❌ 目前無法取得有效的歷史交易日資料，請查看上方具體的錯誤訊息。")
