"""
app.py: 勤務表作成 Streamlit アプリ
"""
import io
import datetime
import streamlit as st

st.set_page_config(page_title="勤務表作成", layout="wide")
st.title("勤務表作成")

# デフォルトは来月
today = datetime.date.today()
if today.month == 12:
    default_year = today.year + 1
    default_month = 1
else:
    default_year = today.year
    default_month = today.month + 1

years = list(range(today.year, today.year + 3))
months = list(range(1, 13))

col1, col2 = st.columns(2)
with col1:
    year = st.selectbox("年", years, index=years.index(default_year))
with col2:
    month = st.selectbox("月", months, index=months.index(default_month), format_func=lambda m: f"{m}月")

st.write(f"対象：**{year}年{month}月**")

if st.button("勤務表を作成する", type="primary"):
    with st.spinner("シフトを計算中..."):
        from agent1_input import build_input
        from agent2_scheduler import build_schedule, get_month_dates
        from agent3_validator import validate
        from agent4_exporter import export_to_excel
        from agent5_designer import apply_design

        input_data = build_input(year, month)
        dates = get_month_dates(year, month)
        schedule = build_schedule(year, month, input_data)
        schedule_data = {
            "year": year,
            "month": month,
            "dates": dates,
            "staff_list": input_data["staff_list"],
            "schedule": schedule,
            "req_map": input_data["req_map"],
        }

        vr = validate(schedule_data)
        _, wb, ws, staff_rows, sum_row, sum_count = export_to_excel(schedule_data, vr)
        apply_design(wb, ws, schedule_data, staff_rows, sum_row, sum_count, vr)

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

    st.success(f"{year}年{month}月の勤務表を生成しました。")

    # 検証サマリー
    required_warnings = [w for w in vr.warnings if "努力目標" not in w]
    effort_warnings = [w for w in vr.warnings if "努力目標" in w]

    if required_warnings:
        st.error(f"⚠️ 必須ルール違反 {len(required_warnings)}件")
        with st.expander("詳細を見る"):
            for w in required_warnings:
                st.write(f"- {w}")
    else:
        st.info("必須ルール違反：なし")

    if effort_warnings:
        with st.expander(f"努力目標未達 {len(effort_warnings)}件"):
            for w in effort_warnings:
                st.write(f"- {w}")

    st.download_button(
        label="📥 Excelをダウンロード",
        data=buf,
        file_name=f"勤務表_{year}年{month}月.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
