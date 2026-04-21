"""
agent1_input.py: 入力整理
data/staff.csv, data/rules.md, data/requests.csv を読み込んで整理する
"""
import csv
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
import datetime

DATA_DIR = Path(__file__).parent / "data"

# シフト定義
SHIFT_HOURS = {
    "早": 8, "日": 8, "A": 4, "P": 4,
    "準": 8, "深": 8, "夕": 4, "送迎": 4,
    "相": 8, "事務": 8, "皿洗い": 4, "休": 0, "": 0
}

# A・P可能スタッフ（Aのみ / A・P両方）
A_ONLY_STAFF = {"大平彩", "川野藍", "石田美歩"}
AP_STAFF = {"谷口直子", "東山鼓", "石橋泉子", "曽我久美子", "塩内由可"}
AP_ALLOWED = A_ONLY_STAFF | AP_STAFF

# 夕シフト可能スタッフ
YUKI_STAFF = {"福山圭子", "塩内由可", "東山鼓"}

# 送迎担当
DELIVERY_STAFF = {"堀太"}

# 皿洗い専属
SARA_STAFF = {"今井順子", "永井仁美", "石橋睦子", "岡本ますみ"}

# 認知症加算対象（日勤必須メンバー）
NINCHI_STAFF = {"出野聡子", "谷口直子", "稲継大稀", "平野由美", "坂本雅代"}

# 看護師（中重度加算）
NURSE_STAFF = {"石橋泉子", "川野藍", "工藤泉", "曽我久美子", "中嶋桜月"}

# 準夜のみOK（深夜不可）
JUN_ONLY_STAFF = {"安部稚畝"}

# A・P禁止スタッフ（明示）
AP_FORBIDDEN = {
    "出野聡子", "大久保夏南", "坂本雅代", "安部稚畝",
    "稲継大稀", "岡田健吾", "岡谷佳代子", "平野由美", "中嶋桜月"
}

# 優先的に週40h確保するスタッフ
PRIORITY_STAFF = {
    "出野聡子", "大久保夏南", "坂本雅代", "安部稚畝",
    "稲継大稀", "岡田健吾", "岡谷佳代子", "平野由美"
}


@dataclass
class StaffInfo:
    name: str
    role: str
    weekly_days: float
    fixed_condition: str
    night_ok: bool
    early_ok: bool
    ninchi: bool
    note: str

    # 派生フラグ
    ap_allowed: bool = False
    a_only: bool = False
    yuki_ok: bool = False
    delivery_only: bool = False
    sara_only: bool = False
    is_nurse: bool = False
    is_priority: bool = False
    count_excluded: bool = False  # 人数カウント除外
    jun_only: bool = False  # 準夜のみOK（深夜不可）


def load_staff() -> list[StaffInfo]:
    path = DATA_DIR / "staff.csv"
    staff_list = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row["名前"].strip()
            weekly_days_str = row["週勤務日数"].strip()
            try:
                weekly_days = float(weekly_days_str)
            except ValueError:
                weekly_days = 0.0

            s = StaffInfo(
                name=name,
                role=row["職種"].strip(),
                weekly_days=weekly_days,
                fixed_condition=row["固定条件"].strip(),
                night_ok=(row["夜勤"].strip() == "可"),
                early_ok=(row["早出"].strip() == "可"),
                ninchi=(row["認知症加算"].strip() == "可"),
                note=row["備考"].strip(),
            )

            # 派生フラグ設定
            s.ap_allowed = name in AP_ALLOWED
            s.a_only = name in A_ONLY_STAFF
            s.yuki_ok = name in YUKI_STAFF
            s.delivery_only = name in DELIVERY_STAFF
            s.sara_only = name in SARA_STAFF
            s.is_nurse = name in NURSE_STAFF
            s.is_priority = name in PRIORITY_STAFF
            s.jun_only = name in JUN_ONLY_STAFF
            if s.jun_only:
                s.night_ok = True  # 準夜のみだが夜勤枠には入れる
            # 管理者・送迎・皿洗い・事務はカウント除外
            s.count_excluded = s.role in {"管理者", "送迎", "皿洗い", "事務"} or name == "稲葉耕太"

            staff_list.append(s)
    return staff_list


@dataclass
class StaffRequest:
    name: str
    date: datetime.date
    req_type: str   # "希望休" or "希望シフト"
    shift: str      # 希望シフト種別（希望シフトの場合）
    note: str


def load_requests() -> list[StaffRequest]:
    path = DATA_DIR / "requests.csv"
    if not path.exists():
        return []
    requests = []
    with open(path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["名前"] is None or row["名前"].strip().startswith("#"):
                continue
            try:
                date = datetime.date.fromisoformat(row["日付"].strip())
            except (ValueError, AttributeError):
                continue
            requests.append(StaffRequest(
                name=row["名前"].strip(),
                date=date,
                req_type=row["希望種別"].strip(),
                shift=row.get("シフト", "").strip(),
                note=row.get("備考", "").strip(),
            ))
    return requests


def load_rules_text() -> str:
    path = DATA_DIR / "rules.md"
    return path.read_text(encoding="utf-8")


def build_input(year: int, month: int) -> dict:
    """全入力データを辞書にまとめて返す"""
    staff_list = load_staff()
    requests = load_requests()
    rules_text = load_rules_text()

    # requests を {名前: {date: StaffRequest}} に変換
    req_map: dict[str, dict[datetime.date, StaffRequest]] = {}
    for r in requests:
        req_map.setdefault(r.name, {})[r.date] = r

    return {
        "year": year,
        "month": month,
        "staff_list": staff_list,
        "req_map": req_map,
        "rules_text": rules_text,
        "constants": {
            "A_ONLY_STAFF": A_ONLY_STAFF,
            "AP_STAFF": AP_STAFF,
            "AP_ALLOWED": AP_ALLOWED,
            "YUKI_STAFF": YUKI_STAFF,
            "SARA_STAFF": SARA_STAFF,
            "NINCHI_STAFF": NINCHI_STAFF,
            "NURSE_STAFF": NURSE_STAFF,
            "AP_FORBIDDEN": AP_FORBIDDEN,
            "PRIORITY_STAFF": PRIORITY_STAFF,
            "SHIFT_HOURS": SHIFT_HOURS,
        }
    }


if __name__ == "__main__":
    import json
    data = build_input(2026, 4)
    print(f"スタッフ数: {len(data['staff_list'])}")
    for s in data["staff_list"]:
        print(f"  {s.name} ({s.role}) 週{s.weekly_days}日 夜勤:{s.night_ok} 早:{s.early_ok}")
