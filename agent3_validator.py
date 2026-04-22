"""
agent3_validator.py: 検証
ルール違反・人員不足をチェックし、警告を出力する
"""
import datetime
import calendar
from agent1_input import (
    SHIFT_HOURS, A_ONLY_STAFF, AP_ALLOWED, AP_FORBIDDEN,
    YUKI_STAFF, NINCHI_STAFF, NURSE_STAFF
)


AM_NORM = 6   # 午前ノルマ
PM_NORM = 6   # 午後ノルマ


class ValidationResult:
    def __init__(self):
        self.warnings: list[str] = []
        # red_cells: {(name, date)} 人員不足でハイライトすべきセル（赤）
        self.red_cells: set[tuple] = set()
        # yellow_cells: {(name, date)} 認知症加算セル（黄）
        self.yellow_cells: set[tuple] = set()
        # pink_cells: {(name, date)} 中重度加算セル（ピンク）
        self.pink_cells: set[tuple] = set()

    def warn(self, msg: str):
        self.warnings.append(msg)
        print(f"[WARNING] {msg}")


def validate(schedule_data: dict) -> ValidationResult:
    year = schedule_data["year"]
    month = schedule_data["month"]
    dates: list[datetime.date] = schedule_data["dates"]
    staff_list = schedule_data["staff_list"]
    schedule: dict = schedule_data["schedule"]
    req_map: dict = schedule_data.get("req_map", {})

    result = ValidationResult()
    staff_by_name = {s.name: s for s in staff_list}

    for d in dates:
        date_str = f"{month}月{d.day}日"

        # ── 早出チェック ────────────────────────────────────────────────
        hayade_count = sum(
            1 for s in staff_list
            if schedule[s.name].get(d) == "早" and not s.count_excluded
        )
        if hayade_count == 0:
            result.warn(f"{date_str}：早出0名")
            for s in staff_list:
                if schedule[s.name].get(d) == "早":
                    result.red_cells.add((s.name, d))
        elif hayade_count > 1:
            result.warn(f"{date_str}：早出{hayade_count}名（1名超過）")

        # ── 準夜勤チェック ────────────────────────────────────────────
        jun_count = sum(1 for s in staff_list if schedule[s.name].get(d) == "準")
        if jun_count == 0:
            result.warn(f"{date_str}：準夜勤0名（必須1名）")
        elif jun_count > 1:
            result.warn(f"{date_str}：準夜勤{jun_count}名（多い）")

        # ── 深夜勤チェック ────────────────────────────────────────────
        deep_count = sum(1 for s in staff_list if schedule[s.name].get(d) == "深")
        if deep_count == 0:
            result.warn(f"{date_str}：深夜勤0名（必須1名）")
        elif deep_count > 1:
            result.warn(f"{date_str}：深夜勤{deep_count}名（多い）")

        # ── 午前カウント ──────────────────────────────────────────────
        am_members = [
            s for s in staff_list
            if not s.count_excluded and schedule[s.name].get(d) in ("日", "A")
        ]
        am_count = len(am_members)
        if am_count < AM_NORM:
            result.warn(f"{date_str}：午前人数不足（{am_count}名）")
            for s in am_members:
                result.red_cells.add((s.name, d))
        elif am_count > AM_NORM:
            result.warn(f"{date_str}：午前人数過剰（{am_count}名）")

        # ── 午後カウント ──────────────────────────────────────────────
        pm_members = [
            s for s in staff_list
            if not s.count_excluded and schedule[s.name].get(d) in ("日", "P")
        ]
        pm_count = len(pm_members)
        if pm_count < PM_NORM:
            result.warn(f"{date_str}：午後人数不足（{pm_count}名）")
            for s in pm_members:
                result.red_cells.add((s.name, d))
        elif pm_count > PM_NORM:
            result.warn(f"{date_str}：午後人数過剰（{pm_count}名）")

        # ── 認知症加算チェック＆黄色セル ──────────────────────────────
        ninchi_workers = [
            s for s in staff_list
            if s.name in NINCHI_STAFF and schedule[s.name].get(d) == "日"
        ]
        if ninchi_workers:
            for s in ninchi_workers:
                result.yellow_cells.add((s.name, d))
        else:
            result.warn(f"{date_str}：認知症加算対象者の日勤なし（努力目標）")

        # ── 中重度加算チェック＆ピンクセル ────────────────────────────
        # 看護師のうちその日に日・A・Pいずれかで勤務している人
        nurses_on_duty = [
            s for s in staff_list
            if s.is_nurse and schedule[s.name].get(d) in ("日", "A", "P")
        ]
        # そのうち日勤の人
        nurses_day = [s for s in nurses_on_duty if schedule[s.name].get(d) == "日"]

        if len(nurses_day) >= 1 and len(nurses_on_duty) >= 2:
            for s in nurses_on_duty:
                result.pink_cells.add((s.name, d))
        else:
            result.warn(f"{date_str}：中重度加算条件未達（看護師：日1名＋日/A/P計2名）（努力目標）")

    # ── 個人ルール違反チェック ───────────────────────────────────────
    for s in staff_list:
        _check_personal_rules(s, dates, schedule, result, month)

    return result


def _check_personal_rules(s, dates: list, schedule: dict, result: ValidationResult, month: int):
    name = s.name

    consecutive = 0
    for i, d in enumerate(dates):
        shift = schedule[name].get(d, "")

        # 深夜勤の翌日チェック
        if i > 0:
            prev_shift = schedule[name].get(dates[i - 1], "")
            if prev_shift == "深" and shift not in ("休", ""):
                result.warn(f"{name}：{month}月{d.day}日 深夜勤翌日に出勤（要休）")

        # 連続出勤カウント（送迎・相・事務・皿洗い・休は含めない）
        if shift in ("早", "日", "A", "P", "準", "深", "夕"):
            consecutive += 1
            if consecutive > 4:
                result.warn(f"{name}：{month}月{d.day}日 連続出勤{consecutive}日目（4日超過）")
        else:
            consecutive = 0

        # A・P禁止チェック
        if name in AP_FORBIDDEN and shift in ("A", "P"):
            result.warn(f"{name}：{month}月{d.day}日 A/P禁止なのに{shift}が入っている")

        # 夕禁止チェック
        if name not in YUKI_STAFF and shift == "夕":
            result.warn(f"{name}：{month}月{d.day}日 夕禁止なのに夕が入っている")

    # 週次 A・P 回数チェック（週2回以上禁止）
    if name in {s.name for s in [s] if s.name in (
        {"谷口直子", "東山鼓", "石橋泉子", "曽我久美子", "塩内由可"}
    )}:
        weeks = _split_weeks(dates)
        for week in weeks:
            ap_count = sum(
                1 for d in week if schedule[name].get(d, "") in ("A", "P")
            )
            if ap_count >= 2:
                result.warn(
                    f"{name}：{month}月 週{week[0].day}〜{week[-1].day} "
                    f"A/P {ap_count}回（週1回まで）"
                )


def _split_weeks(dates: list[datetime.date]) -> list[list[datetime.date]]:
    """月の日付を週単位に分割（月曜始まり）"""
    weeks = []
    current_week = []
    for d in dates:
        current_week.append(d)
        if d.weekday() == 6:  # 日曜でリセット
            weeks.append(current_week)
            current_week = []
    if current_week:
        weeks.append(current_week)
    return weeks


def summarize(schedule_data: dict, vr: ValidationResult):
    """検証サマリーを出力"""
    year = schedule_data["year"]
    month = schedule_data["month"]
    print(f"\n=== 検証結果 {year}年{month}月 ===")
    print(f"警告数: {len(vr.warnings)}")
    print(f"赤セル数: {len(vr.red_cells)}")
    print(f"黄セル数: {len(vr.yellow_cells)}")
    print(f"ピンクセル数: {len(vr.pink_cells)}")
    if not vr.warnings:
        print("問題なし")


if __name__ == "__main__":
    from agent2_scheduler import run_scheduler
    data = run_scheduler(2026, 4)
    vr = validate(data)
    summarize(data, vr)
