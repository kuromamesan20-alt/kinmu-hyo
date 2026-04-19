"""
app.py: 勤務表作成 Streamlit アプリ
"""
import io
import csv
import datetime
import calendar
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="勤務表作成", layout="wide")

DATA_DIR = Path(__file__).parent / "data"

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


def normalize_days(text: str, year: int, month: int) -> list[int]:
    """全角・半角混在の日付文字列を整数リストに変換"""
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    _, last_day = calendar.monthrange(year, month)
    days = []
    for token in text.replace("、", " ").replace(",", " ").replace("　", " ").split():
        try:
            d = int(token)
            if 1 <= d <= last_day:
                days.append(d)
        except ValueError:
            pass
    return sorted(set(days))


def load_staff_names() -> list[str]:
    path = DATA_DIR / "staff.csv"
    names = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["名前"].strip()
            if name:
                names.append(name)
    return names


def load_existing_requests(year: int, month: int) -> dict[str, list[int]]:
    """既存のrequests.csvから指定年月の希望休を読み込む"""
    path = DATA_DIR / "requests.csv"
    result = {}
    if not path.exists():
        return result
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("名前") or row.get("名前", "").strip().startswith("#"):
                continue
            if row.get("希望種別", "").strip() != "希望休":
                continue
            try:
                d = datetime.date.fromisoformat(row["日付"].strip())
            except (ValueError, AttributeError):
                continue
            if d.year == year and d.month == month:
                result.setdefault(row["名前"].strip(), []).append(d.day)
    return result


def save_requests(year: int, month: int, requests: dict[str, list[int]]):
    """指定年月の希望休をrequests.csvに書き込む（他の月のデータは保持）"""
    path = DATA_DIR / "requests.csv"

    # 既存データ読み込み（他の月分を保持）
    existing_rows = []
    comment_lines = []
    if path.exists():
        with open(path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not row.get("名前") or row.get("名前", "").strip().startswith("#"):
                    comment_lines.append(row)
                    continue
                try:
                    d = datetime.date.fromisoformat(row["日付"].strip())
                    if d.year == year and d.month == month:
                        continue  # 今月分は上書きするので除外
                    existing_rows.append(row)
                except (ValueError, AttributeError):
                    continue

    # 新しい希望休を追加
    new_rows = []
    for name, days in requests.items():
        for day in sorted(days):
            new_rows.append({
                "名前": name,
                "日付": f"{year}-{month:02d}-{day:02d}",
                "希望種別": "希望休",
                "シフト": "",
                "備考": "",
            })

    # 書き込み
    all_rows = existing_rows + new_rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["名前", "日付", "希望種別", "シフト", "備考"], extrasaction='ignore')
        writer.writeheader()
        # コメント行を先頭に
        for comment in comment_lines:
            writer.writerow(comment)
        for row in all_rows:
            writer.writerow(row)


# ── タブ ──────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📅 希望休入力", "📊 勤務表作成"])


# ══════════════════════════════════════════════════════════════════════
# TAB1: 希望休入力
# ══════════════════════════════════════════════════════════════════════
with tab1:
    st.header("希望休入力")

    col1, col2 = st.columns(2)
    with col1:
        req_year = st.selectbox("年", years, index=years.index(default_year), key="req_year")
    with col2:
        req_month = st.selectbox("月", months, index=months.index(default_month),
                                 format_func=lambda m: f"{m}月", key="req_month")

    _, last_day = calendar.monthrange(req_year, req_month)
    st.write(f"対象：**{req_year}年{req_month}月**（1〜{last_day}日）")
    st.caption("休みたい日を半角・全角どちらでも入力できます。複数の日はスペースまたはカンマで区切ってください。例：3 15 25 　または　３、１５、２５　※入力された日はExcelで「休」が赤文字で表示されます。")
    st.divider()

    staff_names = load_staff_names()
    existing = load_existing_requests(req_year, req_month)

    inputs = {}
    for name in staff_names:
        existing_days = existing.get(name, [])
        default_text = " ".join(str(d) for d in existing_days)
        val = st.text_input(
            name,
            value=default_text,
            placeholder="例：3, 15, 25",
            key=f"req_{name}",
        )
        inputs[name] = val

    if st.button("保存する", type="primary", key="save_requests"):
        requests_to_save = {}
        errors = []
        for name, text in inputs.items():
            if not text.strip():
                continue
            days = normalize_days(text, req_year, req_month)
            if days:
                requests_to_save[name] = days
            else:
                errors.append(f"{name}：入力値が無効です（{text}）")

        if errors:
            for e in errors:
                st.warning(e)
        else:
            save_requests(req_year, req_month, requests_to_save)
            total = sum(len(v) for v in requests_to_save.values())
            st.success(f"保存しました。{req_year}年{req_month}月の希望休：{total}件")


# ══════════════════════════════════════════════════════════════════════
# TAB2: 勤務表作成
# ══════════════════════════════════════════════════════════════════════
with tab2:
    st.header("勤務表作成")

    col1, col2 = st.columns(2)
    with col1:
        year = st.selectbox("年", years, index=years.index(default_year), key="sched_year")
    with col2:
        month = st.selectbox("月", months, index=months.index(default_month),
                             format_func=lambda m: f"{m}月", key="sched_month")

    st.write(f"対象：**{year}年{month}月**")

    if st.button("勤務表を作成する", type="primary", key="make_schedule"):
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
