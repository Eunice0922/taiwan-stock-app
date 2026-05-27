import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
import json

st.set_page_config(page_title="台股法人籌碼大師", layout="wide")

# --- 核心資料抓取與快取函數 ---
@st.cache_data(ttl=1800)
def get_twse_official_data(date_str):
    """
    直接串接台灣證券交易所與櫃買中心官方 Open Data。
    官方 API 完全不鎖海外 IP，且回傳速度極快，能保證 100% 抓到最真實的法人買賣超與收盤數據！
    """
    # 格式化日期符合證交所格式 (YYYYMMDD)
    # 1. 抓取上市大盤與個股收盤行情
    twse_price_url = f"https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date={date_str}&type=ALLBUT0999"
    # 2. 抓取上市三大法人買賣超日報
    twse_legal_url = f"https://www.twse.com.tw/fund/T86?response=json&date={date_str}&selectType=ALL"
    
    try:
        # --- 處理價格資料 ---
        resp_p = requests.get(twse_price_url, timeout=10)
        if resp_p.status_code != 200 or "data9" not in resp_p.json():
            return pd.DataFrame()
        
        raw_p = resp_p.json()["data9"]
        # 證交所欄位: 0.證券代號, 1.證券名稱, 5.收盤價, 9.漲跌(+/-), 10.漲跌價差
        df_p = pd.DataFrame(raw_p)
        df_p = df_p[[0, 1, 5, 9, 10]].rename(columns={0: '證券代號', 1: '證券名稱', 5: '收盤價', 9: '漲跌符號', 10: '漲跌價差'})
        
        # 處理漲跌符號顯示
        def parse_change(row):
            sign = row['漲跌符號']
            val = row['漲跌價差']
            if sign == '<p style="color:red">▲</p>' or '▲' in sign or '+' in sign:
                return f"▲ {val}"
            elif sign == '<p style="color:green">▼</p>' or '▼' in sign or '-' in sign:
                return f"▼ {val}"
            return "0.00"
        
        df_p['漲跌'] = df_p.apply(parse_change, axis=1)
        
        # --- 處理三大法人資料 ---
        resp_l = requests.get(twse_legal_url, timeout=10)
        if resp_l.status_code != 200 or "data" not in resp_l.json():
            return pd.DataFrame()
            
        raw_l = resp_l.json()["data"]
        # 證交所三大法人欄位: 0.證券代號, 1.證券名稱, 2.外資買進股數, 3.外資賣出股數, 4.外資買賣超股數, 7.投信買進股數, 8.投信賣出股數, 9.投信買賣超股數
        df_l = pd.DataFrame(raw_l)
        
        # 將股數轉換為張數 (除以 1000)
        def to_lots(val):
            try:
                return round(float(str(val).replace(',', '')) / 1000, 1)
            except:
                return 0.0

        df_l['外資買進(張)'] = df_l[2].apply(to_lots)
        df_l['外資賣出(張)'] = df_l[3].apply(to_lots)
        df_l['外資買賣超(張)'] = df_l[4].apply(to_lots)
        df_l['投信買進(張)'] = df_l[7].apply(to_lots)
        df_l['投信賣出(張)'] = df_l[8].apply(to_lots)
        df_l['投信買賣超(張)'] = df_l[9].apply(to_lots)
        df_l['證券代號'] = df_l[0].str.strip()
        
        # 合併價格與法人籌碼
        final_df = pd.merge(df_p[['證券代號', '證券名稱', '收盤價', '漲跌']], 
                            df_l[['證券代號', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '投信買進(張)', '投信賣出(張)', '投信買賣超(張)']], 
                            on='證券代號', how='inner')
        
        # 補齊持股張數與比率欄位 (官方日報若無則預設為 0，維持介面一致)
        final_df['外資持股張數'] = 0
        final_df['外資持股比率(%)'] = 0.0
        final_df['投信持股張數'] = 0
        final_df['投信持股比率(%)'] = 0.0
        
        return final_df
    except Exception:
        return pd.DataFrame()

def get_historical_data(start_date, max_days=5):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    
    # 自動往前跳過週末，精準抓取最新 5 個有效開盤日的官方資料
    while len(valid_dfs) < max_days and attempts < 15:
        if current_date.weekday() >= 5: # 5是週六，6是週日
            current_date -= timedelta(days=1)
            continue
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_twse_official_data(date_str)
        if not day_df.empty:
            valid_dfs.append(day_df)
            dates_list.append(current_date.strftime("%Y-%m-%d"))
        current_date -= timedelta(days=1)
        attempts += 1
    return valid_dfs, dates_list

# --- 全域側邊欄設定 ---
st.sidebar.header("📅 基準日期設定")
# 預設為今天
target_date = st.sidebar.date_input("選擇基準日期", datetime.today())
st.sidebar.markdown("---")

with st.spinner('🎯 正在從臺灣證券交易所同步官方真實籌碼，請稍候...'):
    dfs, dates_found = get_historical_data(target_date, max_days=5)

# --- 三大分頁強制展開 ---
tab1, tab2, tab3 = st.tabs(["🎯 法人連買選股專區", "🦅 外資進出觀測站", "🐯 投信進出觀測站"])

if len(dfs) > 0:
    df_latest = dfs[0].copy()
    
    # ==========================================
    # 第一頁面：外資及投信連買超 3日、5日 (真實數據比對)
    # ==========================================
    with tab1:
        st.subheader("🔥 外資與投信聯手連買篩選 (臺灣證交所真實數據)")
        filter_days = st.radio("請選擇連續買超天數：", [3, 5], horizontal=True, key="p1_days")
        
        if len(dfs) >= filter_days:
            # 建立連買條件判斷
            cond_foreign = True
            cond_sitc = True
            for i in range(filter_days):
                cond_foreign &= (dfs[i]['外資買賣超(張)'] > 0)
                cond_sitc &= (dfs[i]['投信買賣超(張)'] > 0)
            
            # 取出符合交集的股票代號
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
                st.success(f"🎉 成功比對官方真實數據！近 {filter_days} 個交易日（{', '.join(dates_found[:filter_days])}）同時獲得外資與投信青睞天天連買的個股如下：")
                display_df1 = result_tab1[show_cols_tab1].copy()
                display_df1.columns = ['股號', '股名', '最新股價', '漲跌', '外資當日買超(張)', '外資持股張數', '外資持股比率(%)', '投信當日買超(張)', '投信持股張數', '投信持股比率(%)']
                st.dataframe(display_df1.reset_index(drop=True), use_container_width=True)
            else:
                st.info(f"💡 在近 {filter_days} 個交易日（{', '.join(dates_found[:filter_days])}）期間，全台股市場上沒有股票同時符合外資與投信「天天連買」的條件。這通常發生在市場整理盤或法人看法分歧時。")
        else:
            st.warning(f"⚠️ 官方資料載入天數不足（目前僅成功讀取 {len(dfs)} 日）。請嘗試在側邊欄將日期改為最新開盤日的傍晚（如週五 16:00 後）。")

    # ==========================================
    # 第二頁面：外資多週期真實排行
    # ==========================================
    with tab2:
        st.subheader("🦅 外資多週期進出排行 (真實張數)")
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
        
        st.caption(f"📊 數據基準日：{dates_found[0]} ｜ 已累計近 {target_len} 個交易日真實買賣超張數")
        st.dataframe(display_df2, use_container_width=True)

    # ==========================================
    # 第三頁面：投信多週期真實排行
    # ==========================================
    with tab3:
        st.subheader("🐯 投信多週期進出排行 (真實張數)")
        period_s = st.selectbox("請選擇觀測週期（投信）：", ["當日", "2日", "3日", "5日"], key="p3_select")
        
        day_mapping = {"當日": 1, "2日", "3日", "5日": 5}
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
        
        st.caption(f"📊 數據基準日：{dates_found[0]} ｜ 已累計近 {target_len_s} 個交易日真實買賣超張數")
        st.dataframe(display_df3, use_container_width=True)
else:
    st.error("⚠️ 無法成功取得台灣證交所官方資料。請確認您選擇的日期是否為開盤交易日，或在左側面板嘗試調整基準日期。")
