from datetime import datetime
import pytz

# 日本時間を取得
tokyo_time = datetime.now(pytz.timezone('Asia/Tokyo'))
print(f"現在の日本時間は {tokyo_time.strftime('%Y-%m-%d %H:%M:%S')} です！")
