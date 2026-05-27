import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="台股法人雙強連買篩選系統", layout="wide")
st.title("🔥 籌碼雙增選股 - 外資與投信同步連買 3 日")

# 抓取證交所三大法人買賣超數據 (每日下午 3:00 更新)
@st.cache_data(ttl=3600)
def get_twse_data(date_str):
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
            
            # 將數值欄位轉為數字並換算為張數 (股數 / 1000)
            df['收盤價'] = pd.to_numeric(df['收盤價'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            
            # 轉換外資與投信買賣超股數
            foreign_net = pd.to_numeric(df['外資買賣超股數'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            sitc_net = pd.to_numeric(df['投信買賣超股數'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            
            df['外資買賣超(張)'] = (foreign_net / 1000).round(1)
            df['投信買賣超(張)'] = (sitc_net / 1000).round(1)
            
            # 持股比例與張數
            df['持股張數'] = (pd.to_numeric(df['外資持股股數'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0) / 1000).round(0)
            df['外資持股比率(%)'] = pd.to_numeric(df['外資持股比率'].astype(str).str.replace(',', '').str.strip(), errors='coerce').fillna(0)
            
            return df[['證券代號', '證券名稱', '收盤價', '外資買賣超(張)', '投信買賣超(張)', '持股張數', '外資持股比率(%)']]
        else:
            return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

# 核心邏輯：往回尋找 3 個有效的交易日
def get_last_3_trading_days(start_date):
    valid_dfs = []
    dates_list = []
    current_date = start_date
    attempts = 0
    
    # 最多往回嘗試 10 天以避開週休二日與國定假日
    while len(valid_dfs) < 3 and attempts < 10:
        date_str = current_date.strftime("%Y%m%d")
        day_df = get_twse_data(date_str)
        if not day_df.empty:
            valid_dfs.append(day_df)
            dates_list.append(current_date.strftime("%Y-%m-%d"))
        current_date -= timedelta(days=1)
        attempts += 1
        
    return valid_dfs, dates_list

# --- 側邊欄控制面板 ---
st.sidebar.header("⚙️ 篩選設定")
today = datetime.today()
target_date = st.sidebar.date_input("選擇基準日期（通常選今天）", today)

st.sidebar.info("💡 系統會自動由基準日往回推算 3 個開盤交易日，找出外資與投信「天天都在買」的股票。")

# --- 資料運算 ---
with st.spinner('正在分析近 3 個交易日的法人籌碼動向...'):
    dfs, dates_found = get_last_3_trading_days(target_date)

if len(dfs) == 3:
    st.subheader(f"🔍 正在比對以下 3 個交易日的資料：{', '.join(dates_found)}")
    
    # 提取各天的數據
    df_day0 = dfs[0] # 最新一天
    df_day1 = dfs[1] # 昨天
    df_day2 = dfs[2] # 前天
    
    # 將三天的資料透過「證券代號」串聯
    m1 = pd.merge(df_day0, df_day1, on=['證券代號', '證券名稱'], suffixes=('_t0', '_t1'))
    final_merged = pd.merge(m1, df_day2, on=['證券代號', '證券名稱'])
    # 重新命名最後一天的欄位以防混淆
    final_merged = final_merged.rename(columns={'外資買賣超(張)': '外資買賣超(張)_t2', '投信買賣超(張)': '投信買賣超(張)_t2'})
    
    # 核心條件篩選：
    # 外資三天都買超 (>0) 且 投信三天都買超 (>0)
    cond_foreign = (final_merged['外資買賣超(張)_t0'] > 0) & (final_merged['外資買賣超(張)_t1'] > 0) & (final_merged['外資買賣超(張)_t2'] > 0)
    cond_sitc = (final_merged['投信買賣超(張)_t0'] > 0) & (final_merged['投信買賣超(張)_t1'] > 0) & (final_merged['投信買賣超(張)_t2'] > 0)
    
    result_df = final_merged[cond_foreign & cond_sitc].copy()
    
    if not result_df.empty:
        # 整理輸出欄位（顯示最新一天的收盤價、持股資訊，以及三天各自買超張數的加總作為排序依據）
        result_df['近3日外資總買超'] = (result_df['外資買賣超(張)_t0'] + result_df['外資買賣超(張)_t1'] + result_df['外資買賣超(張)_t2']).round(1)
        result_df['近3日投信總買超'] = (result_df['投信買賣超(張)_t0'] + result_df['投信買賣超(張)_t1'] + result_df['投信買賣超(張)_t2']).round(1)
        
        # 挑選最終呈現欄位
        display_cols = [
            '證券代號', '證券名稱', '收盤價_t0', 
            '近3日外資總買超', '近3日投信總買超', 
            '持股張數_t0', '外資持股比率(%)_t0'
        ]
        
        clean_df = result_df[display_cols].copy()
        clean_df.columns = ['股號', '股名', '最新股價', '外資3日累計(張)', '投信3日累計(張)', '外資持股張數', '外資持股比率(%)']
        
        # 依外資買超總量排序
        clean_df = clean_df.sort_values(by='外資3日累計(張)', ascending=False).reset_index(drop=True)
        
        # 顯示成果
        st.success(f"🎉 成功找出 {len(clean_df)} 檔外資與投信同步連買 3 日的黃金交集股！")
        st.dataframe(clean_df, use_container_width=True)
        
        # 下載功能
        csv = clean_df.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 下載雙強連買選股清單 (CSV)", data=csv, file_name=f"雙法人連買3日_{target_date.strftime('%Y%m%d')}.csv", mime='text/csv')
    else:
        st.info("○ 這三天的市場中，沒有任何股票同時符合「外資連買3天」且「投信連買3天」的條件。可以嘗試換個日期基準試試看。")
else:
    st.warning("⚠️ 無法取得足夠的交易日資料，可能因為目前是週末、國定假日，或證交所尚未釋出今日數據（每日 15:00 更新）。請在側邊欄切換基準日期。")
