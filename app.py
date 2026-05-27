import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人連買篩選系統", layout="wide")
st.title("📊 台灣證交所 - 法人買賣超排行與連買篩選")

# 抓取證交所三大法人買賣超排行 (每日下午 3:00 更新)
@st.cache_data(ttl=3600)
def get_twse_data(date_str):
    url = f"https://www.twse.com.tw/rwd/zh/fund/T86KJ7?date={date_str}&selectType=ALL&response=json"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data.get("stat") == "OK":
            # 證交所欄位解析
            cols = data["fields"]
            rows = data["data"]
            df = pd.DataFrame(rows, columns=cols)
            
            # 清理資料格式
            df['證券代號'] = df['證券代號'].str.strip()
            df['證券名稱'] = df['證券名稱'].str.strip()
            
            # 將數值欄位轉為數字
            num_cols = ['收盤價', '外資買進股數', '外資賣出股數', '外資買賣超股數', '投信買進股數', '投信賣出股數', '投信買賣超股數', '外資持股股數', '外資持股比率']
            for col in num_cols:
                if col in df.columns:
                    df[col] = df[col].astype(str).str.replace(',', '').str.strip()
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            # 換算成「張數」 (股數 / 1000)
            df['外資買進(張)'] = (df['外資買進股數'] / 1000).round(1)
            df['外資賣出(張)'] = (df['外資賣出股數'] / 1000).round(1)
            df['外資買賣超(張)'] = (df['外資買賣超股數'] / 1000).round(1)
            df['投信買賣超(張)'] = (df['投信買賣超股數'] / 1000).round(1)
            df['持股張數'] = (df['外資持股股數'] / 1000).round(0)
            
            # 整理出使用者需要的欄位
            result_df = df[['證券代號', '證券名稱', '收盤價', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '投信買賣超(張)', '持股張數', '外資持股比率']].copy()
            result_df.columns = ['股號', '股名', '股價', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '投信買賣超(張)', '持股張數', '持股比率(%)']
            return result_df
        else:
            return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# 核心邏輯：計算連續買超天數
def calculate_consecutive_days(date_obj, days=3):
    current_date = date_obj
    valid_dfs = []
    
    # 往回抓取足夠的交易日資料
    attempts = 0
    while len(valid_dfs) < days and attempts < 10:
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_twse_data(date_str)
        if not day_df.empty:
            valid_dfs.append((date_str, day_df))
        current_date -= timedelta(days=1)
        attempts += 1
        
    if len(valid_dfs) < days:
        return pd.DataFrame(), []
        
    # 以最新一天的資料為主體
    base_df = valid_dfs[0][1].copy()
    
    # 檢查連買條件
    for i in range(days):
        target_df = valid_dfs[i][1]
        # 合併各天的買賣超欄位來做比對
        base_df = base_df.merge(target_df[['股號', '外資買賣超(張)', '投信買賣超(張)']], on='股號', suffixes=('', f'_day{i}'))
        
    return base_df, [v[0] for v in valid_dfs]

# --- 側邊欄控制 ---
st.sidebar.header("⚙️ 條件篩選面板")
today = datetime.today()
# 預設顯示昨天或今天的資料
target_date = st.sidebar.date_input("選擇資料日期", today)
investor_type = st.sidebar.selectbox("觀測法人類別", ["外資", "投信"])
filter_3_days = st.sidebar.checkbox("🔥 僅顯示「連續 3 日買超」股票", value=True)

# --- 讀取與計算資料 ---
with st.spinner('正在從證交所即時運算連買數據中...'):
    base_df, dates_found = calculate_consecutive_days(target_date, days=3)

if not base_df.empty:
    # 決定排序與篩選欄位
    sort_col = '外資買賣超(張)' if investor_type == '外資' else '投信買賣超(張)'
    
    if filter_3_days:
        st.sidebar.success(f"已成功比對交易日：{', '.join(dates_found)}")
        # 連續 3 日買超條件：Day0 > 0 且 Day1 > 0 且 Day2 > 0
        cond_day0 = base_df[f'{sort_col}_day0'] > 0
        cond_day1 = base_df[f'{sort_col}_day1'] > 0
        cond_day2 = base_df[f'{sort_col}_day2'] > 0
        final_df = base_df[cond_day0 & cond_day1 & cond_day2]
        st.subheader(f"🎯 篩選結果：{investor_type} 連續 3 個交易日「皆為買超」的股票")
    else:
        final_df = base_df
        st.subheader(f"📅 {target_date.strftime('%Y-%m-%d')} 當日{investor_type}買賣超排行")

    # 只保留要呈現給使用者的標準美化欄位
    show_cols = ['股號', '股名', '股價', '外資買進(張)', '外資賣出(張)', '外資買賣超(張)', '投信買賣超(張)', '持股張數', '持股比率(%)']
    final_df = final_df[show_cols].sort_values(by=sort_col, ascending=False).reset_index(drop=True)
    
    # 畫面呈現表格
    st.dataframe(final_df, use_container_width=True)
    
    # 提供 Excel/CSV 下載
    csv = final_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 下載此選股清單 (CSV)", data=csv, file_name=f"法人選股_{target_date.strftime('%Y%m%d')}.csv", mime='text/csv')
else:
    st.warning("⚠️ 該日期或週末無交易資料，或者證交所尚未開盤更新（每日 15:00 後更新），請嘗試切換其他日期。")
