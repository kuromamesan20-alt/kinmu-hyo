"""
agent2_scheduler.py: シフト計算
各日を1日ずつ処理する（深夜→早出→日勤の順で1日分を確定）。
これにより連続勤務チェックが正確に機能する。
"""
import datetime
import calendar
from agent1_input import (
    StaffInfo, build_input,
    A_ONLY_STAFF, AP_STAFF, AP_ALLOWED, AP_FORBIDDEN,
    YUKI_STAFF, SARA_STAFF, NINCHI_STAFF, NURSE_STAFF, PRIORITY_STAFF,
    SHIFT_HOURS, WEEKLY_2REST_STAFF, WEEKLY_4WORK_STAFF, AP_NO_LIMIT_STAFF
)

AM_NORM = 6
PM_NORM = 6
WORK_SHIFTS = {"早", "日", "A", "P", "準", "深", "夕"}


def get_month_dates(year: int, month: int) -> list:
    _, last_day = calendar.monthrange(year, month)
    return [datetime.date(year, month, d) for d in range(1, last_day + 1)]


def calc_monthly_target(s: StaffInfo, year: int, month: int) -> float:
    """月間目標を時間で返す（週勤務日数×8h×月日数÷7）"""
    _, last_day = calendar.monthrange(year, month)
    return s.weekly_days * 8 * last_day / 7


def build_schedule(year: int, month: int, input_data: dict) -> dict:
    staff_list = input_data["staff_list"]
    req_map = input_data["req_map"]
    dates = get_month_dates(year, month)

    schedule = {s.name: {d: "" for d in dates} for s in staff_list}

    # Phase1: 固定割り当て（全日一括）
    _phase1_fixed(staff_list, dates, schedule, req_map)

    # 皿洗い4名を毎日1名ずつローテーション
    _assign_sara_rotation(staff_list, dates, schedule, req_map)

    # 稲葉耕太：週5日・全て「相」・休みはどの曜日でも可
    _assign_inaba_rotation(dates, schedule, req_map, year, month)

    # カウント対象スタッフと月間目標
    countable = [s for s in staff_list
                 if not s.count_excluded and not s.sara_only and not s.delivery_only]
    targets = {s.name: calc_monthly_target(s, year, month) for s in countable}

    # Phase2以降: 1日ずつ処理
    for day_idx, d in enumerate(dates):
        days_remaining = len(dates) - day_idx

        # 2a: 深夜（準・深）確保
        for stype in ("深", "準"):
            _assign_night_shift(stype, d, dates, schedule, req_map, staff_list)

        # 2b: 早出確保
        _assign_early_shift(d, dates, schedule, req_map, staff_list)

        # 2c: 日勤（日/A/P）確保
        # 稲葉耕太が休みの日はノルマ+1（早出込み8人体制）
        inaba_off = schedule.get("稲葉耕太", {}).get(d, "") == "休"
        day_am_norm = 7 if inaba_off else AM_NORM
        day_pm_norm = 7 if inaba_off else PM_NORM
        _assign_daytime_shift(d, day_idx, days_remaining, dates, schedule,
                              req_map, countable, targets, day_am_norm, day_pm_norm)

        # 残り未割当を休に確定
        for s in staff_list:
            if schedule[s.name][d] == "":
                schedule[s.name][d] = "休"

    # Phase3: 週2休み厳守スタッフの調整
    _balance_weekly_rest(staff_list, dates, schedule, req_map)

    # Phase3.5: 週4日勤固定スタッフの調整
    _balance_weekly_4work(staff_list, dates, schedule, req_map)

    # Phase4: 中重度加算の看護師配置バランス後処理
    _balance_nurse_coverage(staff_list, dates, schedule, req_map)

    return schedule


# ── Phase 3: 週2休み調整 ──────────────────────────────────────────────

def _get_sunday_weeks(dates):
    """日付リストを日曜始まりの週ごとにグループ化"""
    from collections import defaultdict
    weeks = defaultdict(list)
    for d in dates:
        days_since_sunday = (d.weekday() + 1) % 7
        week_start = d - datetime.timedelta(days=days_since_sunday)
        weeks[week_start].append(d)
    return [sorted(v) for v in sorted(weeks.values())]


def _balance_weekly_rest(staff_list, dates, schedule, req_map):
    """週2休み厳守スタッフの休みを週単位でちょうど2日に調整"""
    two_rest_staff = [s for s in staff_list if s.weekly_2rest]
    if not two_rest_staff:
        return

    weeks = _get_sunday_weeks(dates)

    for s in two_rest_staff:
        for week in weeks:
            # 部分週はスキップ（月初・月末の端数週）
            if len(week) < 7:
                continue

            rest_days = [d for d in week if schedule[s.name][d] == "休"]
            rest_count = len(rest_days)

            if rest_count == 2:
                continue

            def is_kibou_rest(d):
                req = req_map.get(s.name, {}).get(d)
                return req and req.req_type == "希望休"

            def inaba_off_day(d):
                return schedule.get("稲葉耕太", {}).get(d, "") == "休"

            if rest_count > 2:
                # 休みが多い → 余分な休みを勤務に変換（AM_NORMより週2休み厳守を優先）
                excess = rest_count - 2
                # 安部稚畝：稲葉耕太の出勤日の休みを先に変換（稲葉耕太の休日は休みをキープ）
                if s.name == "安部稚畝":
                    rest_days = sorted(rest_days, key=lambda d: (0 if not inaba_off_day(d) else 1))
                changed = 0
                for d in rest_days:
                    if changed >= excess:
                        break
                    if is_kibou_rest(d):
                        continue
                    idx = dates.index(d)
                    prev = schedule[s.name].get(dates[idx - 1], "") if idx > 0 else ""
                    if prev == "深":
                        continue  # 深の翌日は必ず休み・変更不可
                    if prev == "準":
                        # 準の翌日は深でもOK（他に深担当がいない かつ 翌日が休みの場合のみ）
                        deep_taken = any(schedule[st.name].get(d) == "深" for st in staff_list if st.name != s.name)
                        next_d = dates[idx + 1] if idx + 1 < len(dates) else None
                        next_is_rest = next_d is None or schedule[s.name].get(next_d) == "休"
                        if not deep_taken and next_is_rest:
                            schedule[s.name][d] = "深"
                            changed += 1
                        continue
                    # AMノルムを超える日への日勤追加は行わない
                    inaba_off = schedule.get("稲葉耕太", {}).get(d, "") == "休"
                    anbe_active = schedule.get("安部稚畝", {}).get(d, "") in ("早", "日")
                    day_norm = 7 if (inaba_off or anbe_active) else AM_NORM
                    countable_names = {
                        st.name for st in staff_list
                        if not st.count_excluded and not st.sara_only and not st.delivery_only
                    }
                    am_now = sum(
                        1 for st in staff_list
                        if st.name in countable_names and schedule[st.name].get(d) in ("日", "A")
                    )
                    if am_now >= day_norm:
                        continue  # ノルム達成済みなので日勤追加しない
                    # 変換後に連続5日以上にならないか確認
                    before_chain = 0
                    for k in range(idx - 1, -1, -1):
                        if schedule[s.name].get(dates[k], "") in WORK_SHIFTS:
                            before_chain += 1
                        else:
                            break
                    after_chain = 0
                    for k in range(idx + 1, len(dates)):
                        if schedule[s.name].get(dates[k], "") in WORK_SHIFTS:
                            after_chain += 1
                        else:
                            break
                    if before_chain + 1 + after_chain >= 5:
                        continue  # 連続5日以上になるので変換しない
                    schedule[s.name][d] = "日"
                    changed += 1

            else:
                # 休みが少ない → 変更可能な勤務を休みに変換
                deficit = 2 - rest_count
                # まず「日」を優先的に休みに変換
                changeable = [
                    d for d in week
                    if schedule[s.name][d] == "日"
                    and not (req_map.get(s.name, {}).get(d)
                             and req_map[s.name][d].req_type == "希望シフト")
                ]
                # 安部稚畝：稲葉耕太の出勤日を先に休みに変換（稲葉耕太の休日は出勤をキープ）
                if s.name == "安部稚畝":
                    changeable = sorted(changeable, key=lambda d: (0 if not inaba_off_day(d) else 1))
                converted = changeable[:deficit]
                for d in converted:
                    schedule[s.name][d] = "休"
                deficit -= len(converted)
                # 「日」だけでは足りない場合、早出人数が0にならない日の「早」も変換対象に
                if deficit > 0:
                    changeable2 = [
                        d for d in week
                        if schedule[s.name][d] == "早"
                        and not (req_map.get(s.name, {}).get(d)
                                 and req_map[s.name][d].req_type == "希望シフト")
                        and sum(1 for st in staff_list if schedule[st.name][d] == "早") > 1
                    ]
                    for d in changeable2[:deficit]:
                        schedule[s.name][d] = "休"


# ── Phase 3.5: 週4日勤固定スタッフの調整 ───────────────────────────────

def _balance_weekly_4work(staff_list, dates, schedule, req_map):
    """週4日勤固定スタッフ（福山圭子等）の勤務を週単位でちょうど4日に調整。
    夕シフトは既に除外されているため、勤務=日のみ。
    """
    four_work_staff = [s for s in staff_list if s.weekly_4work]
    if not four_work_staff:
        return

    weeks = _get_sunday_weeks(dates)

    for s in four_work_staff:
        for week in weeks:
            if len(week) < 7:
                continue

            def is_kibou_rest(d):
                req = req_map.get(s.name, {}).get(d)
                return req and req.req_type == "希望休"

            work_days = [d for d in week if schedule[s.name][d] in WORK_SHIFTS]
            rest_days = [d for d in week if schedule[s.name][d] == "休"]
            work_count = len(work_days)

            if work_count == 4:
                continue

            if work_count > 4:
                # 勤務過多 → 余分な日を休みに変換
                excess = work_count - 4
                changeable = [
                    d for d in work_days
                    if schedule[s.name][d] == "日"
                    and not is_kibou_rest(d)
                    and not (req_map.get(s.name, {}).get(d)
                             and req_map[s.name][d].req_type == "希望シフト")
                ]
                for d in changeable[:excess]:
                    schedule[s.name][d] = "休"

            else:
                # 勤務不足 → 休みを日勤に変換
                deficit = 4 - work_count
                changeable = [
                    d for d in rest_days
                    if not is_kibou_rest(d)
                ]
                changed = 0
                for d in changeable:
                    if changed >= deficit:
                        break
                    # AMノルムを超える日への追加は行わない
                    idx = dates.index(d)
                    prev = schedule[s.name].get(dates[idx - 1], "") if idx > 0 else ""
                    if prev in ("深", "準"):
                        continue
                    inaba_off = schedule.get("稲葉耕太", {}).get(d, "") == "休"
                    day_norm = 7 if inaba_off else AM_NORM
                    countable_names = {
                        st.name for st in staff_list
                        if not st.count_excluded and not st.sara_only and not st.delivery_only
                    }
                    am_now = sum(
                        1 for st in staff_list
                        if st.name in countable_names and schedule[st.name].get(d) in ("日", "A")
                    )
                    if am_now >= day_norm:
                        continue
                    # 連続5日以上になるか確認
                    before_chain = 0
                    for k in range(idx - 1, -1, -1):
                        if schedule[s.name].get(dates[k], "") in WORK_SHIFTS:
                            before_chain += 1
                        else:
                            break
                    after_chain = 0
                    for k in range(idx + 1, len(dates)):
                        if schedule[s.name].get(dates[k], "") in WORK_SHIFTS:
                            after_chain += 1
                        else:
                            break
                    if before_chain + 1 + after_chain >= 5:
                        continue
                    schedule[s.name][d] = "日"
                    changed += 1


# ── Phase 4: 中重度加算バランス後処理 ───────────────────────────────────

def _balance_nurse_coverage(staff_list, dates, schedule, req_map):
    """
    中重度加算が取れない日を最大化する後処理。
    AM/PMノルムを崩さないため、以下の2操作のみ行う：
      策1: ノルム未達日に看護師を直接追加（ノルム範囲内のみ）
      策2: 3名以上日と不足日で「看護師(日)↔非看護師(日)」スワップ
           ※日↔日のみでAM/PM両方±1 → バランス保持
    """
    nurses = [s for s in staff_list if s.is_nurse]
    non_a_nurses = [s for s in nurses if not s.a_only]
    countable = [s for s in staff_list if not s.count_excluded and not s.sara_only and not s.delivery_only]
    non_nurses = [s for s in countable if not s.is_nurse
                  and not s.sara_only and not s.delivery_only]

    def _am(d):
        return sum(1 for s in countable if schedule[s.name].get(d, "") in ("日", "A"))

    def _pm(d):
        return sum(1 for s in countable if schedule[s.name].get(d, "") in ("日", "P"))

    def _norm(d):
        inaba_off = schedule.get("稲葉耕太", {}).get(d, "") == "休"
        return 7 if inaba_off else AM_NORM

    def _nurses_on(d):
        return [s for s in nurses if schedule[s.name].get(d, "") in ("日", "A", "P")]

    def _req_rest(name, d):
        return (name in req_map and req_map[name].get(d) is not None
                and req_map[name][d].req_type == "希望休")

    def _can_work(name, d, pretend_rest=None):
        if _req_rest(name, d):
            return False
        idx = dates.index(d)
        if idx > 0:
            prev = dates[idx - 1]
            ps = schedule[name].get(prev, "") if prev != pretend_rest else "休"
            if ps in ("深", "準"):
                return False
        consecutive = 0
        for i in range(idx - 1, max(idx - 5, -1), -1):
            dd = dates[i]
            sh = schedule[name].get(dd, "") if dd != pretend_rest else "休"
            if sh in ("早", "日", "A", "P", "準", "深", "夕"):
                consecutive += 1
            else:
                break
        return consecutive < 4

    def _is_met(d):
        nods = _nurses_on(d)
        return (any(schedule[s.name].get(d) == "日" for s in nods) and len(nods) >= 2)

    for _ in range(100):
        deficit_days = [d for d in dates if not _is_met(d)]
        if not deficit_days:
            break
        surplus_days = sorted(
            [d for d in dates if len(_nurses_on(d)) >= 3],
            key=lambda d: len(_nurses_on(d)), reverse=True
        )
        improved = False

        for tgt in deficit_days:
            tgt_norm = _norm(tgt)
            tgt_am = _am(tgt)
            tgt_pm = _pm(tgt)
            tgt_nurses = _nurses_on(tgt)
            need_day = not any(schedule[s.name].get(tgt) == "日" for s in tgt_nurses)

            # ── 策1a: AM/PMともにノルム未達 → 日勤追加 ─────────────────
            if tgt_am < tgt_norm and tgt_pm < tgt_norm:
                for nurse in non_a_nurses:
                    if schedule[nurse.name].get(tgt, "") not in ("休", ""):
                        continue
                    if not _can_work(nurse.name, tgt):
                        continue
                    if tgt_am + 1 > tgt_norm or tgt_pm + 1 > tgt_norm:
                        continue
                    schedule[nurse.name][tgt] = "日"
                    improved = True
                    break

            # ── 策1b: PM不足・AM満員 → P追加（日勤ナース不要の場合のみ）─
            if not improved and tgt_am >= tgt_norm and tgt_pm < tgt_norm and not need_day:
                for nurse in non_a_nurses:
                    if schedule[nurse.name].get(tgt, "") not in ("休", ""):
                        continue
                    if not nurse.ap_allowed or nurse.name in AP_FORBIDDEN:
                        continue
                    if not _can_work(nurse.name, tgt):
                        continue
                    if tgt_pm + 1 > tgt_norm:
                        continue
                    schedule[nurse.name][tgt] = "P"
                    improved = True
                    break

            if improved:
                break

            # ── 策2: 余剰日と不足日で 日(看護師)↔日(非看護師) スワップ──
            for src in surplus_days:
                if src == tgt:
                    continue
                src_nurses_on = _nurses_on(src)
                if len(src_nurses_on) < 3:
                    continue

                for nurse in src_nurses_on:
                    if nurse.a_only:
                        continue
                    if schedule[nurse.name].get(src, "") != "日":
                        continue
                    if schedule[nurse.name].get(tgt, "") != "休":
                        continue
                    if need_day and nurse.a_only:
                        continue
                    # src: 加算条件が崩れないか
                    remaining = [s for s in src_nurses_on if s.name != nurse.name]
                    if not any(schedule[s.name].get(src) == "日" for s in remaining):
                        continue
                    if len(remaining) < 2:
                        continue
                    if not _can_work(nurse.name, tgt, pretend_rest=src):
                        continue
                    # 非看護師スワップ相手（tgt で日、src で休）
                    for nx in non_nurses:
                        if schedule[nx.name].get(tgt, "") != "日":
                            continue
                        if schedule[nx.name].get(src, "") != "休":
                            continue
                        if _req_rest(nx.name, src):
                            continue
                        if not _can_work(nx.name, src, pretend_rest=tgt):
                            continue
                        # 日↔日スワップ → AM/PM両日で不変
                        schedule[nurse.name][src] = "休"
                        schedule[nurse.name][tgt] = "日"
                        schedule[nx.name][src] = "日"
                        schedule[nx.name][tgt] = "休"
                        improved = True
                        break
                    if improved:
                        break
                if improved:
                    break
            if improved:
                break

        if not improved:
            break


# ── Phase 1: 固定割り当て ─────────────────────────────────────────────

def _assign_sara_rotation(staff_list, dates, schedule, req_map):
    """
    皿洗い4名（今井順子・永井仁美・石橋睦子・岡本ますみ）を
    毎日必ず1名だけローテーションで割り当てる。
    各人の週勤務日数を参考に月間出勤可能日数の上限を設ける。
    希望休の日はその人を候補から除外する。
    """
    sara_names = ["今井順子", "永井仁美", "石橋睦子", "岡本ますみ"]
    sara_staff = {s.name: s for s in staff_list if s.name in sara_names}
    sara_names = [n for n in sara_names if n in sara_staff]  # staff.csvに存在する人のみ

    import calendar as _cal
    if not dates:
        return
    year, month = dates[0].year, dates[0].month
    _, last_day = _cal.monthrange(year, month)
    weeks = last_day / 7
    quotas = {name: round(sara_staff[name].weekly_days * weeks) for name in sara_names}
    work_counts = {name: 0 for name in sara_names}

    # 全員を休で初期化
    for name in sara_names:
        for d in dates:
            schedule[name][d] = "休"

    # 毎日1名だけ割り当て（ローテーション）
    idx = 0
    for d in dates:
        # 希望休の人は除外
        kibou_rest_names = {
            name for name in sara_names
            if req_map.get(name, {}).get(d) and req_map[name][d].req_type == "希望休"
        }

        # quota未達かつ希望休でない候補
        cands = [
            name for name in sara_names
            if work_counts[name] < quotas[name] and name not in kibou_rest_names
        ]
        if not cands:
            # quota達成済みの中から希望休でない人を選ぶ
            cands = [name for name in sara_names if name not in kibou_rest_names]
        if not cands:
            # 全員希望休（稀なケース）→ スキップ
            continue

        ordered = sara_names[idx:] + sara_names[:idx]
        chosen = next((n for n in ordered if n in cands), cands[0])

        schedule[chosen][d] = "皿洗い"
        work_counts[chosen] += 1
        idx = (sara_names.index(chosen) + 1) % len(sara_names)


def _assign_inaba_rotation(dates, schedule, req_map, year, month):
    """
    稲葉耕太：週5日勤務・全て「相」・休みの曜日は固定しない。
    月間目標日数（21〜22日）を均等分散で達成する。
    希望休があればそれを優先。
    """
    import calendar as _cal
    _, last_day = _cal.monthrange(year, month)
    target = round(5.0 * last_day / 7)  # 週5日 × 月週数 = 21〜22日

    # 希望休を先に確定
    for d in dates:
        req = req_map.get("稲葉耕太", {}).get(d)
        if req and req.req_type == "希望休":
            schedule["稲葉耕太"][d] = "休"

    # 既確定の休み以外の候補日
    candidates = [d for d in dates if schedule["稲葉耕太"][d] == ""]

    already_work = sum(1 for d in dates if schedule["稲葉耕太"][d] == "相")
    needed = max(0, target - already_work)

    # 均等間隔で勤務日を選択
    if needed >= len(candidates):
        work_days = set(candidates)
    else:
        step = len(candidates) / needed
        work_days = set()
        i = 0.0
        while len(work_days) < needed and int(i) < len(candidates):
            work_days.add(candidates[int(i)])
            i += step

    for d in candidates:
        schedule["稲葉耕太"][d] = "相" if d in work_days else "休"


def _phase1_fixed(staff_list, dates, schedule, req_map):
    for s in staff_list:
        for d in dates:
            req = req_map.get(s.name, {}).get(d)
            if req and req.req_type == "希望休":
                schedule[s.name][d] = "休"; continue
            if req and req.req_type == "希望シフト" and req.shift:
                schedule[s.name][d] = req.shift; continue

            wd = d.weekday()
            if s.name == "堀太":
                schedule[s.name][d] = "送迎" if wd in (6,0,3) else "休"; continue
            if s.sara_only:
                continue  # 皿洗いは _assign_sara_rotation で一括処理
            if s.name == "田村まどか":
                schedule[s.name][d] = "日" if wd == 2 else "休"; continue
            if s.name == "石田美歩":
                schedule[s.name][d] = "A" if wd in (1,4) else "休"; continue
            if s.name == "大平彩":
                schedule[s.name][d] = "A" if wd in (0,3) else "休"; continue
            if s.name == "辻明子":
                schedule[s.name][d] = "日" if wd in (5,6) else "休"; continue
            if s.name == "稲葉耕太":
                continue  # 月間ローテで別途割り当て（Phase2以降）
            if s.name == "安部稚畝":
                if d.day == 1 or d.day == dates[-1].day:
                    schedule[s.name][d] = "事務"; continue
            if s.name == "工藤泉":
                if wd not in (0,1,2,3,4):
                    schedule[s.name][d] = "休"; continue

    # 坂本雅代：21〜24日の間の1日に「事務」（希望休でない最初の空き日）
    if "坂本雅代" in schedule:
        year, month = dates[0].year, dates[0].month
        for day_num in range(21, 25):
            d_cand = datetime.date(year, month, day_num)
            if d_cand not in dates:
                continue
            req = req_map.get("坂本雅代", {}).get(d_cand)
            if req and req.req_type == "希望休":
                continue
            if schedule["坂本雅代"].get(d_cand, "") == "":
                schedule["坂本雅代"][d_cand] = "事務"
                break

    # 岡谷佳代子・大久保夏南：奇数月→岡谷、偶数月→大久保に月1回「計」
    year, month = dates[0].year, dates[0].month
    kei_name = "岡谷佳代子" if month % 2 == 1 else "大久保夏南"
    if kei_name in schedule:
        for day_num in [15, 14, 16, 13, 17, 12, 18, 11, 19, 10, 20, 9, 21, 8, 22]:
            if day_num > dates[-1].day:
                continue
            d_cand = datetime.date(year, month, day_num)
            if d_cand not in dates:
                continue
            req = req_map.get(kei_name, {}).get(d_cand)
            if req and req.req_type == "希望休":
                continue
            if schedule[kei_name].get(d_cand, "") == "":
                schedule[kei_name][d_cand] = "計"
                break


# ── ユーティリティ ────────────────────────────────────────────────────

def _prev_shift(name, d, dates, schedule):
    idx = dates.index(d)
    return schedule[name].get(dates[idx-1], "") if idx > 0 else ""


def _consecutive_before(name, d, dates, schedule):
    """dの直前の連続出勤日数"""
    idx = dates.index(d)
    count = 0
    for i in range(idx-1, max(-1, idx-6), -1):
        if schedule[name].get(dates[i], "") in WORK_SHIFTS:
            count += 1
        else:
            break
    return count


def _can_assign(name, d, dates, schedule, req_map, require_empty=True):
    """この日にシフトを入れられるか"""
    if require_empty and schedule[name][d] != "":
        return False
    if req_map.get(name, {}).get(d) and req_map[name][d].req_type == "希望休":
        return False
    if _prev_shift(name, d, dates, schedule) == "深":
        return False  # 深の翌日は休必須
    if _prev_shift(name, d, dates, schedule) == "準":
        return False  # 準の翌日は休か深のみ（深は別途割り当て）
    if _consecutive_before(name, d, dates, schedule) >= 4:
        return False
    return True


def _week_ap_count(name, d, dates, schedule):
    """この日が属する週のA/P回数を返す（月曜始まり）"""
    # 週の月曜を探す
    monday = d - datetime.timedelta(days=d.weekday())
    count = 0
    for dd in dates:
        if monday <= dd < monday + datetime.timedelta(days=7):
            if schedule[name].get(dd, "") in ("A", "P"):
                count += 1
    return count


def _next_day_occupied(name, d, dates, schedule):
    """翌日が既に確定している（深を入れると翌日休めない）"""
    idx = dates.index(d)
    if idx + 1 >= len(dates):
        return False
    return schedule[name].get(dates[idx+1], "") not in ("", "休")


def _night_would_overflow(s, d, dates, schedule):
    """深/準を入れると翌日が強制休みになり、週2休みを超えるか判定"""
    if not s.weekly_2rest:
        return False
    idx = dates.index(d)
    if idx + 1 >= len(dates):
        return False
    next_d = dates[idx + 1]

    def week_start_of(dt):
        days_since_sun = (dt.weekday() + 1) % 7
        return dt - datetime.timedelta(days=days_since_sun)

    # 翌日が既に休みなら準/深を入れても追加の休みは発生しない
    if schedule[s.name].get(next_d, "") == "休":
        return False

    # 翌日が属する週の休み数を確認
    next_week_start = week_start_of(next_d)
    next_week_end = next_week_start + datetime.timedelta(days=7)
    next_week_days = [dd for dd in dates if next_week_start <= dd < next_week_end]
    next_rest = sum(1 for dd in next_week_days if schedule[s.name].get(dd) == "休")
    # 翌日の強制休みを加えた合計が2を超えるなら割り当てない
    return next_rest + 1 > 2


# ── 2a: 夜勤 ─────────────────────────────────────────────────────────

def _night_rest_in_next_week(s, d, dates, schedule):
    """翌日が属する週の確定休み数を返す（フォールバック選択の優先度に使用）"""
    idx = dates.index(d)
    if idx + 1 >= len(dates):
        return 0
    next_d = dates[idx + 1]
    def week_start_of(dt):
        days_since_sun = (dt.weekday() + 1) % 7
        return dt - datetime.timedelta(days=days_since_sun)
    nws = week_start_of(next_d)
    nwe = nws + datetime.timedelta(days=7)
    nw_days = [dd for dd in dates if nws <= dd < nwe]
    return sum(1 for dd in nw_days if schedule[s.name].get(dd) == "休")


def _assign_night_shift(stype, d, dates, schedule, req_map, staff_list):
    if any(schedule[s.name][d] == stype for s in staff_list):
        return
    night_ok = [s for s in staff_list
                if s.night_ok and not s.sara_only and not s.delivery_only
                and s.name != "稲葉耕太"
                and not (s.jun_only and stype == "深")]
    if stype == "深":
        # 深は準の翌日もOK（深の翌日はNG）
        # ただし翌日が希望休の人には深を入れない（希望休が強制休みと重なるのを防ぐ）
        def _next_day_is_kibou_rest(s, d):
            idx = dates.index(d)
            if idx + 1 >= len(dates):
                return False
            next_d = dates[idx + 1]
            req = req_map.get(s.name, {}).get(next_d)
            return req and req.req_type == "希望休"

        cands = [s for s in night_ok
                 if schedule[s.name][d] == ""
                 and not (req_map.get(s.name, {}).get(d) and req_map[s.name][d].req_type == "希望休")
                 and _prev_shift(s.name, d, dates, schedule) != "深"
                 and _consecutive_before(s.name, d, dates, schedule) < 4
                 and not _next_day_occupied(s.name, d, dates, schedule)
                 and not _next_day_is_kibou_rest(s, d)
                 and not _night_would_overflow(s, d, dates, schedule)]
        if not cands:
            # フォールバック: overflow以外の条件をパスする候補（最後の手段）
            cands = [s for s in night_ok
                     if schedule[s.name][d] == ""
                     and not (req_map.get(s.name, {}).get(d) and req_map[s.name][d].req_type == "希望休")
                     and _prev_shift(s.name, d, dates, schedule) != "深"
                     and _consecutive_before(s.name, d, dates, schedule) < 4
                     and not _next_day_occupied(s.name, d, dates, schedule)
                     and not _next_day_is_kibou_rest(s, d)]
    else:
        # 準：WEEKLY_2REST_STAFFは、準を入れると翌日強制休みになるため
        # その週の確定休み＋準翌日休みが2日を超える場合は除外
        cands = [s for s in night_ok
                 if _can_assign(s.name, d, dates, schedule, req_map)
                 and not _next_day_occupied(s.name, d, dates, schedule)
                 and not _night_would_overflow(s, d, dates, schedule)]
        if not cands:
            # フォールバック: overflow以外の条件をパスする候補（最後の手段）
            cands = [s for s in night_ok
                     if _can_assign(s.name, d, dates, schedule, req_map)
                     and not _next_day_occupied(s.name, d, dates, schedule)]
    # 翌日週の確定休み数が少ない順（Phase3が修正しやすい候補を優先）→ 夜勤回数少ない順
    cands.sort(key=lambda s: (
        _night_rest_in_next_week(s, d, dates, schedule),
        sum(1 for dd in dates if schedule[s.name].get(dd) in ("準","深")),
    ))
    if cands:
        schedule[cands[0].name][d] = stype


# ── 2b: 早出 ─────────────────────────────────────────────────────────

def _assign_early_shift(d, dates, schedule, req_map, staff_list):
    early_ok = [s for s in staff_list
                if s.early_ok and not s.sara_only and not s.delivery_only
                and s.name != "稲葉耕太"]
    if any(schedule[s.name][d] == "早" for s in early_ok):
        return
    cands = [s for s in early_ok
             if _can_assign(s.name, d, dates, schedule, req_map)]
    cands.sort(key=lambda s: sum(1 for dd in dates if schedule[s.name].get(dd) == "早"))
    if cands:
        schedule[cands[0].name][d] = "早"


# ── 2c: 日勤 ─────────────────────────────────────────────────────────

def _assign_daytime_shift(d, day_idx, days_remaining, dates, schedule,
                           req_map, countable, targets,
                           am_norm=AM_NORM, pm_norm=PM_NORM):
    am_count = sum(1 for s in countable
                   if schedule[s.name].get(d, "") in ("日", "A"))
    pm_count = sum(1 for s in countable
                   if schedule[s.name].get(d, "") in ("日", "P"))

    avail = [s for s in countable
             if _can_assign(s.name, d, dates, schedule, req_map)]

    # 中重度加算：この日に既に何人のナースが日/A/P で入っているか
    nurses_on_day = sum(
        1 for st in countable
        if st.is_nurse and schedule[st.name].get(d, "") in ("日", "A", "P")
    )
    nurses_day_now = sum(
        1 for st in countable
        if st.is_nurse and schedule[st.name].get(d, "") == "日"
    )

    def score(s):
        work_so_far = sum(SHIFT_HOURS.get(schedule[s.name].get(dd, ""), 0) for dd in dates)
        needed = max(0, targets[s.name] - work_so_far)
        urgency = needed / days_remaining if days_remaining > 0 else 0
        pri = (0 if s.is_priority else 0.1) + (0 if s.name in NINCHI_STAFF else 0.05)
        # 中重度加算バランス（優先度調整のみ、ハードキャップはPhase4で）
        nurse_adj = 0.0
        if s.is_nurse:
            if nurses_on_day == 0:
                nurse_adj = 0.7
            elif nurses_on_day == 1:
                nurse_adj = 0.5 if nurses_day_now == 0 else 0.3
            else:
                nurse_adj = -0.3  # 3人目以降は後回し（但し目標未達なら自然と上がる）
        return -(urgency + pri + nurse_adj)

    avail.sort(key=score)

    for s in avail:
        if am_count >= am_norm and pm_count >= pm_norm:
            break

        work_so_far = sum(SHIFT_HOURS.get(schedule[s.name].get(dd, ""), 0) for dd in dates)
        if work_so_far >= targets[s.name]:
            schedule[s.name][d] = "休"
            continue

        need_am = am_count < am_norm
        need_pm = pm_count < pm_norm

        # A/P週制限チェック（AP_NO_LIMIT_STAFFは制限なし）
        ap_weekly_full = (
            s.name in AP_STAFF
            and s.name not in A_ONLY_STAFF
            and s.name not in AP_NO_LIMIT_STAFF
            and _week_ap_count(s.name, d, dates, schedule) >= 1
        )
        # A_ONLYはAのみ可能だが週複数回OK（制限対象外）

        if need_am and not need_pm:
            can_a = s.ap_allowed and s.name not in AP_FORBIDDEN
            if not can_a or (ap_weekly_full and s.name not in A_ONLY_STAFF):
                # Aを入れられない → 日勤にすると午後が増えるのでスキップ
                schedule[s.name][d] = "休"
                continue
            shift = "A"
        elif not need_am and need_pm:
            can_p = (s.ap_allowed and s.name not in AP_FORBIDDEN
                     and s.name not in A_ONLY_STAFF)
            if not can_p or ap_weekly_full:
                schedule[s.name][d] = "休"
                continue
            shift = "P"
        else:
            shift = _pick_shift(s, am_count, pm_count, am_norm, pm_norm)
            # 週AP制限で A/P → 日 に変換
            if shift in ("A", "P") and ap_weekly_full and s.name not in A_ONLY_STAFF:
                shift = "日"

        schedule[s.name][d] = shift
        if shift in ("日", "A"):
            am_count += 1
        if shift in ("日", "P"):
            pm_count += 1


def _pick_shift(s, am, pm, am_norm=AM_NORM, pm_norm=PM_NORM):
    name = s.name
    if s.a_only: return "A"
    if name == "東山鼓":
        if am < am_norm and pm < pm_norm: return "日"
        if pm < pm_norm: return "P"
        return "夕"
    if name == "塩内由可":
        if am < am_norm and pm < pm_norm: return "日"
        if pm < pm_norm: return "P"
        return "日"
    if name == "福山圭子":
        if am < am_norm and pm < pm_norm: return "日"
        return "夕"
    if name in AP_STAFF and name not in {"東山鼓","塩内由可"}:
        if am < am_norm and pm < pm_norm: return "日"
        if pm < pm_norm: return "P"
        return "A"
    if am < am_norm and pm < pm_norm: return "日"
    if am < am_norm:
        can_a = s.ap_allowed and name not in AP_FORBIDDEN and name not in A_ONLY_STAFF
        return "A" if can_a else "日"
    if pm < pm_norm:
        can_p = s.ap_allowed and name not in AP_FORBIDDEN and name not in A_ONLY_STAFF
        return "P" if can_p else "日"
    return "日"


# ── エントリポイント ──────────────────────────────────────────────────

def run_scheduler(year: int, month: int) -> dict:
    input_data = build_input(year, month)
    schedule = build_schedule(year, month, input_data)
    return {
        "year": year,
        "month": month,
        "dates": get_month_dates(year, month),
        "staff_list": input_data["staff_list"],
        "schedule": schedule,
        "req_map": input_data["req_map"],
    }


if __name__ == "__main__":
    result = run_scheduler(2026, 4)
    dates = result["dates"]
    print(f"\n=== {result['year']}年{result['month']}月 ===")
    for s in result["staff_list"][:8]:
        row = " ".join((result["schedule"][s.name][d] or "?").ljust(4) for d in dates[:10])
        print(f"{s.name:10s}: {row}")
