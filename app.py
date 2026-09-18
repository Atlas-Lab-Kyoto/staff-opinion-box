import streamlit as st
from streamlit_gsheets import GSheetsConnection
import google.generativeai as genai
import json
from datetime import datetime
import pandas as pd

# ページ設定
st.set_page_config(page_title="スタッフ意見・改善要望箱", page_icon="💡", layout="wide")

# APIキーの設定
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-3-flash-preview")

# スプレッドシート接続
conn = st.connection("gsheets", type=GSheetsConnection)

# サイドバー：管理者ログイン
st.sidebar.title("🔒 管理者エリア")
admin_password = st.sidebar.text_input("パスワードを入力", type="password")
is_admin = (admin_password == st.secrets["ADMIN_PASSWORD"])

if not is_admin:
    # ----------------------------------------------------
    # 一般スタッフ用：投稿フォーム
    # ----------------------------------------------------
    st.title("💡 スタッフ意見・改善要望箱")
    st.write("職場の改善案や気になる点、設備の問題などを気軽にお寄せください。（匿名で送信されます）")

    with st.form("opinion_form"):
        user_opinion = st.text_area("意見・要望内容", height=150, placeholder="例：令和なのに雨漏りしてます…")
        submitted = st.form_submit_button("送信する")

    if submitted:
        if not user_opinion.strip():
            st.warning("内容を入力してください。")
        else:
            with st.spinner("AIが内容を解析し、登録処理を行っています..."):
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
                - category: 上記選択肢から最も適切なカテゴリ名
                - urgency: 低 / 中 / 高 / 要緊急対応 のいずれか
                - summary: 客観的な要約（1-2文）
                - action_plan: 会社や経営層へ提出・交渉するための丁寧で角が立たない提案文案
                """

                try:
                    response = model.generate_content(
                        prompt,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    res_json = json.loads(response.text)

                    # 現在日時
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # データフレーム化
                    new_data = pd.DataFrame([{
                        "timestamp": now_str,
                        "opinion": user_opinion,
                        "category": res_json.get("category", "その他・アイデア"),
                        "urgency": res_json.get("urgency", "中"),
                        "summary": res_json.get("summary", ""),
                        "action_plan": res_json.get("action_plan", ""),
                        "status": "未対応"  # 初期ステータス
                    }])

                    # 既存データ取得と追加
                    existing_data = conn.read(ttl=0)
                    updated_data = pd.concat([existing_data, new_data], ignore_index=True)

                    # スプレッドシート更新
                    conn.update(data=updated_data)

                    st.success("ご意見ありがとうございます！正常に送信されました。")
                    st.balloons()
                except Exception as e:
                    st.error(f"送信処理中にエラーが発生しました: {e}")

else:
    # ----------------------------------------------------
    # 管理者用：ダッシュボード
    # ----------------------------------------------------
    st.title("📊 意見・改善要望 管理ダッシュボード")

    # データの読み込み
    try:
        df = conn.read(ttl=0)
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        df = pd.DataFrame()

    if not df.empty:
        # status列が存在しない場合の補完処理
        if "status" not in df.columns:
            df["status"] = "未対応"

        # サイドバーフィルター
        st.sidebar.markdown("---")
        st.sidebar.subheader("🔍 表示フィルター")
        status_filter = st.sidebar.multiselect(
            "表示するステータス",
            options=["未対応", "対応中", "対応済み"],
            default=["未対応", "対応中"]  # 初期状態では完了分を除外
        )

        # フィルター適用
        filtered_df = df[df["status"].isin(status_filter)]

        # 要緊急対応のアラート表示（未対応・対応中のみチェック）
        urgent_items = filtered_df[filtered_df["urgency"] == "要緊急対応"]
        if not urgent_items.empty:
            st.error(f"🚨 **【要緊急対応】の意見が {len(urgent_items)} 件あります！**")
            for _, item in urgent_items.iterrows():
                with st.expander(f"⚠️ {item.get('timestamp')} | カテゴリ: {item.get('category')}", expanded=True):
                    st.write(f"**要約:** {item.get('summary')}")
                    st.write(f"**原文:** {item.get('opinion')}")
                    st.write(f"**対応方針案:** {item.get('action_plan')}")
            st.markdown("---")

        # 全体メトリクス
        col1, col2, col3 = st.columns(3)
        col1.metric("表示中の件数", f"{len(filtered_df)} 件")
        top_cat = filtered_df["category"].mode()[0] if not filtered_df.empty and "category" in filtered_df.columns else "なし"
        col2.metric("最多カテゴリ", top_cat)
        col3.metric("要緊急件数", f"{len(urgent_items)} 件")

        st.markdown("---")

        # 意見一覧とステータス更新
        st.subheader("📋 意見一覧")

        for idx, row in filtered_df.iloc[::-1].iterrows():  # 新しい順に表示
            urgency_color = {
                "要緊急対応": "🔴",
                "高": "🟠",
                "中": "🟡",
                "低": "🔵"
            }.get(row.get("urgency"), "⚪")

            status_badge = {
                "未対応": "⏳ 未対応",
                "対応中": "🔄 対応中",
                "対応済み": "✅ 対応済み"
            }.get(row.get("status"), "⏳ 未対応")

            with st.expander(f"{urgency_color} [{status_badge}] {row.get('timestamp')} | {row.get('category')} | 緊急度: {row.get('urgency')}"):
                st.write(f"**【要約】** {row.get('summary')}")
                st.write(f"**【原文】** {row.get('opinion')}")
                st.info(f"**【経営・管理層向け対応方針案】**\n\n{row.get('action_plan')}")

                # ステータス変更フォーム
                new_status = st.selectbox(
                    "ステータス変更",
                    options=["未対応", "対応中", "対応済み"],
                    index=["未対応", "対応中", "対応済み"].index(row.get("status", "未対応")),
                    key=f"status_select_{idx}"
                )

                if new_status != row.get("status"):
                    if st.button("ステータスを更新", key=f"btn_{idx}"):
                        df.at[idx, "status"] = new_status
                        conn.update(data=df)
                        st.success(f"ステータスを「{new_status}」に変更しました！")
                        st.rerun()

        st.markdown("---")
        st.subheader("📊 全データ一覧（スプレッドシート同期）")
        st.dataframe(filtered_df)

    else:
        st.info("まだ投稿された意見はありません。")
