"""
main.py: 勤務表自動生成システム「くろまめさん」
python main.py              → 当月の勤務表を生成
python main.py 2026 4       → 指定年月の勤務表を生成
"""
import sys
import datetime

def main():
    if len(sys.argv) == 3:
        year = int(sys.argv[1])
        month = int(sys.argv[2])
    else:
        today = datetime.date.today()
        year = today.year
        month = today.month

    print(f"\n{'='*50}")
    print(f" 勤務表自動生成システム「くろまめさん」")
    print(f" 対象: {year}年{month}月")
    print(f"{'='*50}")

    # agent1: 入力整理
    print("\n[1/5] 入力データ読み込み中...")
    from agent1_input import build_input
    input_data = build_input(year, month)
    print(f"  スタッフ数: {len(input_data['staff_list'])}名")
    print(f"  希望申請数: {sum(len(v) for v in input_data['req_map'].values())}件")

    # agent2: シフト計算
    print("\n[2/5] シフト計算中...")
    from agent2_scheduler import build_schedule, get_month_dates
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
    print(f"  {len(dates)}日分のシフトを計算しました")

    # agent3: 検証
    print("\n[3/5] ルール検証中...")
    from agent3_validator import validate, summarize
    vr = validate(schedule_data)
    summarize(schedule_data, vr)

    # agent4: Excel出力
    print("\n[4/5] Excel出力中...")
    from agent4_exporter import export_to_excel
    path, wb, ws, staff_rows, sum_row, sum_count = export_to_excel(schedule_data, vr)

    # agent5: デザイン適用
    print("\n[5/5] デザイン適用中...")
    from agent5_designer import apply_design
    apply_design(wb, ws, schedule_data, staff_rows, sum_row, sum_count, vr)
    wb.save(path)

    print(f"\n{'='*50}")
    print(f" 完了！")
    print(f" 出力先: {path}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
