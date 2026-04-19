"""
agent4_exporter.py: Excel出力
スケジュールデータをExcelに書き込む（スタイルなし）
"""
import datetime
import calendar
from pathlib import Path
import openpyxl
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 行レイアウト
HEADER_ROW = 1     # 列ヘッダー（日付・曜日）
STAFF_START_ROW = 2  # スタッフ行開始
NAME_COL = 1       # 名前列（A列）
DATE_START_COL = 2  # 日付開始列（B列）

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]


def export_to_excel(schedule_data: dict, validation_result=None) -> Path:
    year = schedule_data["year"]
    month = schedule_data["month"]
    dates: list[datetime.date] = schedule_data["dates"]
    staff_list = schedule_data["staff_list"]
    schedule: dict = schedule_data["schedule"]

    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}年{month}月"

    # ── ヘッダー行（名前列） ──────────────────────────────────────────
    ws.cell(row=HEADER_ROW, column=NAME_COL, value="氏名")
    ws.cell(row=HEADER_ROW + 1, column=NAME_COL, value="職種")

    # ── 日付ヘッダー ─────────────────────────────────────────────────
    for i, d in enumerate(dates):
        col = DATE_START_COL + i
        ws.cell(row=HEADER_ROW, column=col, value=d.day)
        ws.cell(row=HEADER_ROW + 1, column=col, value=WEEKDAY_JP[d.weekday()])

    # ── スタッフ行 ────────────────────────────────────────────────────
    staff_rows: dict[str, int] = {}
    for row_idx, s in enumerate(staff_list):
        row = STAFF_START_ROW + 1 + row_idx  # +1 for weekday row
        staff_rows[s.name] = row
        ws.cell(row=row, column=NAME_COL, value=s.name)
        ws.cell(row=row, column=NAME_COL + 0).comment = None  # placeholder

        for i, d in enumerate(dates):
            col = DATE_START_COL + i
            shift = schedule[s.name].get(d, "")
            ws.cell(row=row, column=col, value=shift)

    # ── 集計行 ────────────────────────────────────────────────────────
    summary_start_row = STAFF_START_ROW + 1 + len(staff_list) + 1
    summary_labels = ["早", "午前(日+A)", "午後(日+P)", "準", "深", "夕・送迎"]
    summary_keys = ["早", "am", "pm", "準", "深", "夕送迎"]

    ws.cell(row=summary_start_row - 1, column=NAME_COL, value="──集計──")

    for j, (label, key) in enumerate(zip(summary_labels, summary_keys)):
        sum_row = summary_start_row + j
        ws.cell(row=sum_row, column=NAME_COL, value=label)

        for i, d in enumerate(dates):
            col = DATE_START_COL + i
            count = _count_summary(key, d, staff_list, schedule)
            ws.cell(row=sum_row, column=col, value=count)

    # ── メタデータ（行・列マップをシートに保存） ──────────────────────
    wb.custom_doc_props = {}  # placeholder

    output_path = OUTPUT_DIR / f"勤務表_{year}年{month}月.xlsx"
    wb.save(output_path)
    print(f"[export] 保存: {output_path}")
    return output_path, wb, ws, staff_rows, summary_start_row, len(summary_labels)


def _count_summary(key: str, d: datetime.date, staff_list: list, schedule: dict) -> int:
    """集計行のカウント"""
    if key == "早":
        return sum(1 for s in staff_list if schedule[s.name].get(d) == "早")
    if key == "am":
        return sum(
            1 for s in staff_list
            if not s.count_excluded and schedule[s.name].get(d) in ("日", "A")
        )
    if key == "pm":
        return sum(
            1 for s in staff_list
            if not s.count_excluded and schedule[s.name].get(d) in ("日", "P")
        )
    if key == "準":
        return sum(1 for s in staff_list if schedule[s.name].get(d) == "準")
    if key == "深":
        return sum(1 for s in staff_list if schedule[s.name].get(d) == "深")
    if key == "夕送迎":
        return sum(
            1 for s in staff_list if schedule[s.name].get(d) in ("夕", "送迎")
        )
    return 0


if __name__ == "__main__":
    from agent2_scheduler import run_scheduler
    data = run_scheduler(2026, 4)
    result = export_to_excel(data)
    print("Export done:", result[0])
