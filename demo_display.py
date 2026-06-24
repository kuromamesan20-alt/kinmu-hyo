"""Instagramライブ用のデモ表示設定。

内部計算・保存データは本名のまま扱い、画面とExcelだけ仮名表示にする。
本番表示へ戻すときは DEMO_MODE = False に変更する。
"""
from typing import Optional

DEMO_MODE = False

DEMO_NAME_MAP = {
    "稲葉耕太": "黒豆さん太郎",
    "出野聡子": "黒豆さん花子",
    "大久保夏南": "黒豆さん美咲",
    "坂本雅代": "黒豆さん和子",
    "谷口直子": "黒豆さん直子",
    "東山鼓": "黒豆さん鼓子",
    "安部稚畝": "黒豆さん一郎",
    "稲継大稀": "黒豆さん大輔",
    "岡田健吾": "黒豆さん健太",
    "岡谷佳代子": "黒豆さん佳代",
    "大平彩": "黒豆さん彩",
    "塩内由可": "黒豆さん由香",
    "田村まどか": "黒豆さんまどか",
    "辻明子": "黒豆さん明子",
    "福山圭子": "黒豆さん圭子",
    "岡野陽子": "黒豆さん陽子",
    "石橋泉子": "黒豆さん泉",
    "川野藍": "黒豆さん藍",
    "工藤泉": "黒豆さんいずみ",
    "曽我久美子": "黒豆さん久美",
    "中嶋桜月": "黒豆さん桜",
    "佐々木優奈": "黒豆さん優奈",
    "石田美歩": "黒豆さん美歩",
    "堀太": "黒豆さん次郎",
    "今井順子": "黒豆さん順子",
    "永井仁美": "黒豆さん仁美",
    "石橋睦子": "黒豆さん睦子",
    "岡本ますみ": "黒豆さんますみ",
    "礒田真祐": "黒豆さん三郎",
}


def _fallback_display_name(name: str) -> str:
    number = sum(ord(char) for char in name) % 100 + 1
    return f"黒豆さんスタッフ{number:02d}"


def display_name(name: str) -> str:
    if not DEMO_MODE:
        return name
    return DEMO_NAME_MAP.get(name, _fallback_display_name(name))


def display_names(names: Optional[list[str]] = None) -> dict[str, str]:
    if not DEMO_MODE:
        return {}
    target_names = names if names is not None else list(DEMO_NAME_MAP)
    return {name: display_name(name) for name in target_names}


def unknown_demo_names(names: list[str]) -> list[str]:
    if not DEMO_MODE:
        return []
    return [name for name in names if name not in DEMO_NAME_MAP]


def display_text(text: str, names: Optional[list[str]] = None) -> str:
    if not DEMO_MODE:
        return text
    result = text
    target_names = set(DEMO_NAME_MAP)
    if names is not None:
        target_names.update(names)
    name_map = {name: display_name(name) for name in target_names}
    for real_name, fake_name in sorted(name_map.items(), key=lambda item: len(item[0]), reverse=True):
        result = result.replace(real_name, fake_name)
    return result
