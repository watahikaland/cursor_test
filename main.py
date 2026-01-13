import random
from datetime import datetime
import pytz

# 日本時間を取得
tokyo_time = datetime.now(pytz.timezone('Asia/Tokyo'))
date_str = tokyo_time.strftime('%Y-%m-%d %H:%M:%S')

# ラッキーカラーのリスト
colors = ["レッド", "ブルー", "イエロー", "グリーン", "ピンク", "オレンジ", "パープル", "ゴールド"]
lucky_color = random.choice(colors)

print(f"--- 診断結果 ---")
print(f"現在時刻: {date_str}")
print(f"今日のあなたのラッキーカラーは… 【{lucky_color}】 です！")
print(f"----------------")
