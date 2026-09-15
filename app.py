"""
app.py: 勤務表作成 Streamlit アプリ
"""
import io
import csv
import datetime
import calendar
from pathlib import Path
from typing import Optional
import streamlit as st
from demo_display import DEMO_MODE, display_name, display_names, display_text, unknown_demo_names

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
    for token in text.replace("、", " ").replace("，", " ").replace(",", " ").replace("　", " ").split():
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


# agent2_scheduler.WORK_SHIFTS のうち、希望出勤として入力を受け付けるもの
ALLOWED_SHIFTS = ["早", "日", "A", "P", "準", "深", "夕"]


def load_existing_requests(year: int, month: int) -> tuple[dict[str, list[int]], dict[str, dict[int, str]]]:
    """既存のrequests.csvから指定年月の希望休・希望シフトを読み込む"""
    path = DATA_DIR / "requests.csv"
    offs: dict[str, list[int]] = {}
    shifts: dict[str, dict[int, str]] = {}
    if not path.exists():
        return offs, shifts
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get("名前") or row.get("名前", "").strip().startswith("#"):
                continue
            req_type = row.get("希望種別", "").strip()
            if req_type not in ("希望休", "希望シフト"):
                continue
            try:
                d = datetime.date.fromisoformat(row["日付"].strip())
            except (ValueError, AttributeError):
                continue
            if d.year != year or d.month != month:
                continue
            name = row["名前"].strip()
            if req_type == "希望休":
                offs.setdefault(name, []).append(d.day)
            else:
                shift = row.get("シフト", "").strip()
                if shift:
                    shifts.setdefault(name, {})[d.day] = shift
    return offs, shifts


FIELDNAMES = ["名前", "日付", "希望種別", "シフト", "備考"]
GITHUB_OWNER = "kuromamesan20-alt"
GITHUB_REPO  = "kinmu-hyo"
GITHUB_PATH  = "data/requests.csv"


def _build_csv_str(comment_lines: list, all_rows: list) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDNAMES, extrasaction="ignore")
    writer.writeheader()
    for row in comment_lines:
        writer.writerow(row)
    for row in all_rows:
        writer.writerow(row)
    return buf.getvalue()


def _push_to_github(content: str):
    """GitHub APIでrequests.csvを更新（GITHUB_TOKENがある場合のみ）"""
    import urllib.request, urllib.error, json, base64
    try:
        token = st.secrets["GITHUB_TOKEN"]
    except (KeyError, FileNotFoundError):
        return  # ローカル実行時はスキップ

    api_url = (f"https://api.github.com/repos/{GITHUB_OWNER}"
               f"/{GITHUB_REPO}/contents/{GITHUB_PATH}")
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }

    # 現在のSHAを取得
    sha = None
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            sha = json.loads(resp.read())["sha"]
    except urllib.error.HTTPError:
        pass

    # ファイルを更新
    body: dict = {
        "message": "希望休・希望出勤データを更新",
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        body["sha"] = sha

    try:
        req = urllib.request.Request(
            api_url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as e:
        st.warning(f"GitHubへの保存に失敗しました（{e.code}）。ローカルには保存済みです。")


def save_requests(year: int, month: int, requests: dict[str, list[int]],
                  shift_requests: Optional[dict[str, dict[int, str]]] = None):
    """指定年月の希望休・希望シフトをrequests.csvに書き込み、GitHubにも反映する"""
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

    # 新しい希望休・希望シフトを追加
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
    for name, day_shifts in (shift_requests or {}).items():
        for day in sorted(day_shifts):
            new_rows.append({
                "名前": name,
                "日付": f"{year}-{month:02d}-{day:02d}",
                "希望種別": "希望シフト",
                "シフト": day_shifts[day],
                "備考": "",
            })

    all_rows = existing_rows + new_rows
    csv_str = _build_csv_str(comment_lines, all_rows)

    # ローカルに書き込み
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(csv_str)

    # GitHubにも反映（クラウド実行時）
    _push_to_github(csv_str)


# ── タブ ──────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📅 希望入力", "📊 勤務表作成"])


# ══════════════════════════════════════════════════════════════════════
# TAB1: 希望休・希望シフト入力
# ══════════════════════════════════════════════════════════════════════
with tab1:
    st.header("希望入力")
    if DEMO_MODE:
        st.info("デモ表示中：スタッフ名は仮名で表示しています。")

    col1, col2 = st.columns(2)
    with col1:
        req_year = st.selectbox("年", years, index=years.index(default_year), key="req_year")
    with col2:
        req_month = st.selectbox("月", months, index=months.index(default_month),
                                 format_func=lambda m: f"{m}月", key="req_month")

    _, last_day = calendar.monthrange(req_year, req_month)
    st.write(f"対象：**{req_year}年{req_month}月**（1〜{last_day}日）")
    st.caption("**希望休**：休みたい日を半角・全角どちらでも入力できます。複数の日はスペースまたはカンマで区切ってください。例：3 15 25 　または　３、１５、２５　※入力された日はExcelで「休」が赤文字で表示されます。")
    st.caption(
        "**希望出勤**：日付を選んだあと、その日の勤務をプルダウンで選んでください。"
        f"使える勤務：{' / '.join(ALLOWED_SHIFTS)}"
    )
    st.divider()

    staff_names = load_staff_names()
    unknown_names = unknown_demo_names(staff_names)
    if unknown_names:
        st.warning(f"デモ用の仮名が未登録のスタッフが{len(unknown_names)}名います。汎用仮名で表示します。")
    existing_offs, existing_shifts = load_existing_requests(req_year, req_month)

    inputs = {}
    shift_inputs = {}
    for name in staff_names:
        st.markdown(f"**{display_name(name)}**")
        col_off, col_shift = st.columns(2)
        with col_off:
            inputs[name] = st.text_input(
                "希望休",
                value=" ".join(str(d) for d in existing_offs.get(name, [])),
                placeholder="例：3, 15, 25",
                key=f"req_{req_year}_{req_month}_{name}",
            )
        with col_shift:
            existing_day_shifts = existing_shifts.get(name, {})
            selected_shift_days = st.multiselect(
                "希望出勤日",
                options=list(range(1, last_day + 1)),
                default=sorted(existing_day_shifts),
                format_func=lambda d: f"{d}日",
                key=f"reqshift_days_{req_year}_{req_month}_{name}",
            )
            day_shifts: dict[int, str] = {}
            if selected_shift_days:
                shift_cols = st.columns(min(4, len(selected_shift_days)))
                for idx, day in enumerate(sorted(selected_shift_days)):
                    current_shift = existing_day_shifts.get(day, "日")
                    if current_shift not in ALLOWED_SHIFTS:
                        current_shift = "日"
                    with shift_cols[idx % len(shift_cols)]:
                        day_shifts[day] = st.selectbox(
                            f"{day}日の勤務",
                            ALLOWED_SHIFTS,
                            index=ALLOWED_SHIFTS.index(current_shift),
                            key=f"reqshift_{req_year}_{req_month}_{name}_{day}",
                        )
            shift_inputs[name] = day_shifts

    if st.button("保存する", type="primary", key="save_requests"):
        requests_to_save = {}
        shifts_to_save = {}
        errors = []
        for name in staff_names:
            text = inputs[name]
            if text.strip():
                days = normalize_days(text, req_year, req_month)
                if days:
                    requests_to_save[name] = days
                else:
                    errors.append(f"{display_name(name)}：希望休の入力値が無効です（{text}）")

            day_shifts = shift_inputs[name]
            if day_shifts:
                shifts_to_save[name] = day_shifts

            # 同じ日に希望休と希望出勤が入っている場合はエラー
            conflicts = sorted(set(requests_to_save.get(name, [])) & set(shifts_to_save.get(name, {})))
            if conflicts:
                errors.append(
                    f"{display_name(name)}：{('・'.join(f'{d}日' for d in conflicts))}が"
                    "希望休と希望出勤の両方に入っています"
                )

        if errors:
            for e in errors:
                st.warning(e)
        else:
            save_requests(req_year, req_month, requests_to_save, shifts_to_save)
            total_off = sum(len(v) for v in requests_to_save.values())
            total_shift = sum(len(v) for v in shifts_to_save.values())
            st.success(
                f"保存しました。{req_year}年{req_month}月の希望休：{total_off}件／"
                f"希望出勤：{total_shift}件"
            )


# ══════════════════════════════════════════════════════════════════════
# TAB2: 勤務表作成
# ══════════════════════════════════════════════════════════════════════
with tab2:
    st.header("勤務表作成")
    if DEMO_MODE:
        st.info("デモ表示中：スタッフ名は仮名で表示しています。")

    from agent1_input import build_input

    col1, col2 = st.columns(2)
    with col1:
        year = st.selectbox("年", years, index=years.index(default_year), key="sched_year")
    with col2:
        month = st.selectbox("月", months, index=months.index(default_month),
                             format_func=lambda m: f"{m}月", key="sched_month")

    st.write(f"対象：**{year}年{month}月**")

    input_data = build_input(year, month)
    staff_names = [s.name for s in input_data["staff_list"]]
    prev_month_last_day = datetime.date(year, month, 1) - datetime.timedelta(days=1)
    night_staff_names = [
        s.name
        for s in input_data["staff_list"]
        if s.night_ok
        and (
            not s.jun_only
            or (
                s.name == "安部稚畝"
                and (prev_month_last_day.year, prev_month_last_day.month) == (2026, 5)
            )
        )
    ]
    prev_deep_options = [""] + night_staff_names
    prev_deep_staff = st.selectbox(
        "前月末日の深夜担当者",
        prev_deep_options,
        format_func=lambda name: "選択なし" if name == "" else display_name(name),
        key="prev_month_deep_staff",
    )
    st.caption(
        f"{prev_month_last_day.month}月{prev_month_last_day.day}日に深夜だった人を選ぶと、"
        f"{month}月1日が自動で休みになります。"
    )

    if st.button("勤務表を作成する", type="primary", key="make_schedule"):
        with st.spinner("シフトを計算中..."):
            from agent2_scheduler import build_schedule, get_month_dates
            from agent3_validator import validate
            from agent4_exporter import export_to_excel
            from agent5_designer import apply_design

            input_data["prev_month_deep_staff"] = prev_deep_staff or None
            dates = get_month_dates(year, month)
            schedule = build_schedule(year, month, input_data)
            schedule_data = {
                "year": year,
                "month": month,
                "dates": dates,
                "staff_list": input_data["staff_list"],
                "schedule": schedule,
                "req_map": input_data["req_map"],
                "display_names": display_names(staff_names),
                "prev_month_deep_staff": prev_deep_staff or None,
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
                    st.write(f"- {display_text(w, staff_names)}")
        else:
            st.info("必須ルール違反：なし")

        if effort_warnings:
            with st.expander(f"努力目標未達 {len(effort_warnings)}件"):
                for w in effort_warnings:
                    st.write(f"- {display_text(w, staff_names)}")

        st.download_button(
            label="📥 Excelをダウンロード",
            data=buf,
            file_name=f"勤務表_{year}年{month}月{'_デモ' if DEMO_MODE else ''}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
