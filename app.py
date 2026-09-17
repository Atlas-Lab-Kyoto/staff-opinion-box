import json
from datetime import datetime
import pandas as pd
import streamlit as st
import google.generativeai as genai
from streamlit_gsheets import GSheetsConnection

# --- ページ基本設定 ---
st.set_page_config(
    page_title="スタッフ意見・改善要望箱",
    page_icon="🗣️",
    layout="wide"
)

# --- Gemini API & Google Sheets 接続設定 ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
conn = st.connection("gsheets", type=GSheetsConnection)

# --- サイドバー：管理者ログイン・画面切り替え ---
st.sidebar.title("🔐 管理者メニュー")
admin_password_input = st.sidebar.text_input("管理者パスワード", type="password")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin123")  # Secrets未設定時のデフォルト

if admin_password_input == ADMIN_PASSWORD:
    st.sidebar.success("管理者として認証されました")
    mode = st.sidebar.radio("画面選択", ["投稿フォーム（スタッフ用）", "管理ダッシュボード（代表専用）"])
else:
    mode = "投稿フォーム（スタッフ用）"


# ==========================================
# 1. 投稿フォーム（スタッフ用画面）
# ==========================================
if mode == "投稿フォーム（スタッフ用）":
    st.title("🗣️ スタッフ意見・改善要望の投稿箱")
    st.caption("匿名で安全に送信されます。AIが自動整理して代表窓口に届きます。")

    with st.form("opinion_form", clear_on_submit=True):
        user_opinion = st.text_area(
            "職場への意見や改善してほしいことを入力してください",
            height=150,
            placeholder="例: シフトの確定が遅くて予定が立てづらいです。もう少し早めに共有してもらえると助かります。"
        )
        submitted = st.form_submit_button("この内容で送信する")

    if submitted:
        if not user_opinion.strip():
            st.warning("内容を入力してから送信してください。")
        else:
            with st.spinner("AIが意見を分類・整理して送信中..."):
                try:
                    # Gemini API による自動解析
                    model = genai.GenerativeModel("gemini-3-flash-preview")
                    
                    prompt = f"""
                    あなたは職場の改善意見を分析する優秀なアシスタントです。
                    以下のスタッフの意見を解析し、指定のJSON形式のみで返答してください。

                    【カテゴリー選択肢】
                    - 店舗設備・環境
                    - 業務運用・作業フロー
                    - 人員・シフト・労働環境
                    - 商品・サービス・接客
                    - その他・アイデア

                    ※カテゴリ名は上記リストの文字列そのものだけを出力し、数字や記号（「1. 」など）は絶対に含めないでください。

                    【入力】
                    {user_opinion}

                    【出力キー】
                    - category: 上記1〜7から最も適切なカテゴリ名
                    - urgency: 低 / 中 / 高 / 要緊急対応 のいずれか
                    - summary: 客観的な要約（1-2文）
                    - action_plan: 会社や経営層へ提出・交渉するための丁寧で角が立たない提案文案
                    """

                    response = model.generate_content(
                        prompt,
                        generation_config={"response_mime_type": "application/json"}
                    )

                    result = json.loads(response.text)

                    # 保存データの作成
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    new_data = pd.DataFrame([{
                        "timestamp": now_str,
                        "category": result.get("category", "改善アイデア・その他"),
                        "urgency": result.get("urgency", "中"),
                        "summary": result.get("summary", ""),
                        "action_plan": result.get("action_plan", ""),
                        "original_text": user_opinion
                    }])

                    # Google スプレッドシートへの追記
                    existing_df = conn.read(ttl=0)
                    # voted列などで以前発生した型不一致を防ぐため文字列キャスト
                    existing_df = existing_df.astype(str)
                    
                    updated_df = pd.concat([existing_df, new_data], ignore_index=True)
                    conn.update(data=updated_df)

                    st.success("ご意見ありがとうございました！正常に受け付けました。")

                except Exception as e:
                    st.error(f"送信処理中にエラーが発生しました: {e}")


# ==========================================
# 2. 管理ダッシュボード（代表専用画面）
# ==========================================
elif mode == "管理ダッシュボード（代表専用）":
    st.title("📊 意見・改善要望 管理ダッシュボード")
    
    try:
        df = conn.read(ttl=0)
        
        if df.empty or "timestamp" not in df.columns:
            st.info("まだ投稿された意見はありません。")
        else:
            # --- 1. 緊急対応アラート ---
            urgent_df = df[df["urgency"] == "要緊急対応"]
            if not urgent_df.empty:
                st.error(f"🚨 **【要緊急対応】の意見が {len(urgent_df)} 件あります！**")
                for _, row in urgent_df.iterrows():
                    st.warning(
                        f"**投稿日時**: {row['timestamp']} | **カテゴリ**: {row['category']}\n\n"
                        f"**要約**: {row['summary']}\n\n"
                        f"**原文**: {row['original_text']}"
                    )
                st.markdown("---")

            # --- 2. メトリクス表示 ---
            col1, col2, col3 = st.columns(3)
            col1.metric("総投稿件数", f"{len(df)} 件")
            top_cat = df["category"].mode()[0] if not df["category"].empty else "-"
            col2.metric("最多カテゴリ", top_cat)
            col3.metric("要緊急件数", f"{len(urgent_df)} 件")

            st.markdown("---")

            # --- 3. 一覧表示とフィルター ---
            st.subheader("📋 投稿データ一覧")
            
            categories = ["すべて"] + list(df["category"].unique())
            selected_cat = st.selectbox("カテゴリで絞り込み", categories)
            
            if selected_cat != "すべて":
                filtered_df = df[df["category"] == selected_cat]
            else:
                filtered_df = df

            st.dataframe(
                filtered_df[["timestamp", "category", "urgency", "summary", "action_plan"]],
                use_container_width=True
            )

            # --- 4. 会社提出用提案文の確認・コピーエリア ---
            st.markdown("---")
            st.subheader("💼 会社提出用テキスト案の確認")
            
            if not filtered_df.empty:
                selected_idx = st.number_input(
                    "詳細を表示するデータ番号（上の一覧のインデックス番号）",
                    min_value=0,
                    max_value=len(filtered_df) - 1,
                    step=1
                )
                
                target_row = filtered_df.iloc[selected_idx]
                
                col_left, col_right = st.columns(2)
                with col_left:
                    st.markdown("**【スタッフの原文】**")
                    st.info(target_row["original_text"])
                
                with col_right:
                    st.markdown("**【会社交渉用・提案文章案】**")
                    st.success(target_row["action_plan"])

    except Exception as e:
        st.error(f"データ取得中にエラーが発生しました: {e}")
