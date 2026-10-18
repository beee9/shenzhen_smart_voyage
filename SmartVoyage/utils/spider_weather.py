import os
import requests
import mysql.connector
from datetime import datetime, timedelta
import schedule
import time
import json
import gzip
import pytz

# 配置
API_KEY = os.getenv("QWEATHER_SPIDER_API_KEY", "")
city_codes = {
    "北京": "101010100",
    "上海": "101020100",
    "杭州": "101280101",
    "南京": "101190101",
    "深圳宝安": "101280605"
}
BASE_URL = "https://m7487r6ych.re.qweatherapi.com/v7/weather/30d"
TZ = pytz.timezone('Asia/Shanghai')  # 使用上海时区

# MySQL 配置
db_config = {
    "host": "localhost",
    "user": "smart_yoyage",
    "password": "123456",
    "database": "travel_rag",
    "charset": "utf8mb4"
}

def connect_db():
    return mysql.connector.connect(**db_config)
#利用和风api获取对应城市的天气
def fetch_weather_data(city, location):
    headers = {
        "X-QW-Api-Key": API_KEY,
        "Accept-Encoding": "gzip"
    }
    url = f"{BASE_URL}?location={location}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        if response.headers.get('Content-Encoding') == 'gzip':
            data = gzip.decompress(response.content).decode('utf-8')
        else:
            data = response.text
        return json.loads(data)
    except requests.RequestException as e:
        print(f"请求 {city} 天气数据失败: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"{city} JSON 解析错误: {e}, 响应内容: {response.text[:500]}...")
        return None
    except gzip.BadGzipFile:
        print(f"{city} 数据未正确解压，尝试直接解析: {response.text[:500]}...")
        return json.loads(response.text) if response.text else None

def get_latest_update_time(cursor, city):
    cursor.execute("SELECT MAX(update_time) FROM weather_data WHERE city = %s", (city,))
    result = cursor.fetchone()
    return result[0] if result[0] else None
# 根据update_time 来决定要不要更新weather_data 表的数据 ,如果update_time 为空, 或者>24H ,就得更新数据
def should_update_data(latest_time, force_update=False):
    """
    如果没有更新时间 或者 更新时间大于24小时 或者 force_update=True，就返回True，就去更新数据库中的这个城市的天气数据。
    其他情况返回False，表示不更新数据库中的数据。
    :param latest_time: 某个城市最新的更新时间
    :param force_update: 默认否
    :return: 是 或者 否 true or false
    """
    if force_update:
        return True
    if not latest_time:
        return True
    current_time = datetime.now(TZ)
    latest_time = latest_time.replace(tzinfo=TZ)
    #3600是啥意思? 60*60 ,一个小时
    return (current_time - latest_time).total_seconds() / 3600 >= 24

def store_weather_data(conn, cursor, city, data):
    if not data or data.get("code") != "200":
        print(f"{city} 数据无效，跳过存储。")
        return

    daily_data = data.get("daily", [])
    update_time = datetime.fromisoformat(data.get("updateTime").replace("+08:00", "+08:00")).replace(tzinfo=TZ)

    for day in daily_data:
        fx_date = datetime.strptime(day["fxDate"], "%Y-%m-%d").date()
        values = (
            city, fx_date,
            day.get("sunrise"), day.get("sunset"),
            day.get("moonrise"), day.get("moonset"),
            day.get("moonPhase"), day.get("moonPhaseIcon"),
            day.get("tempMax"), day.get("tempMin"),
            day.get("iconDay"), day.get("textDay"),
            day.get("iconNight"), day.get("textNight"),
            day.get("wind360Day"), day.get("windDirDay"), day.get("windScaleDay"), day.get("windSpeedDay"),
            day.get("wind360Night"), day.get("windDirNight"), day.get("windScaleNight"), day.get("windSpeedNight"),
            day.get("precip"), day.get("uvIndex"),
            day.get("humidity"), day.get("pressure"),
            day.get("vis"), day.get("cloud"),
            update_time
        )
        insert_query = """
        INSERT INTO weather_data (
            city, fx_date, sunrise, sunset, moonrise, moonset, moon_phase, moon_phase_icon,
            temp_max, temp_min, icon_day, text_day, icon_night, text_night,
            wind360_day, wind_dir_day, wind_scale_day, wind_speed_day,
            wind360_night, wind_dir_night, wind_scale_night, wind_speed_night,
            precip, uv_index, humidity, pressure, vis, cloud, update_time
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            sunrise = VALUES(sunrise), sunset = VALUES(sunset), moonrise = VALUES(moonrise),
            moonset = VALUES(moonset), moon_phase = VALUES(moon_phase), moon_phase_icon = VALUES(moon_phase_icon),
            temp_max = VALUES(temp_max), temp_min = VALUES(temp_min), icon_day = VALUES(icon_day),
            text_day = VALUES(text_day), icon_night = VALUES(icon_night), text_night = VALUES(text_night),
            wind360_day = VALUES(wind360_day), wind_dir_day = VALUES(wind_dir_day), wind_scale_day = VALUES(wind_scale_day),
            wind_speed_day = VALUES(wind_speed_day), wind360_night = VALUES(wind360_night),
            wind_dir_night = VALUES(wind_dir_night), wind_scale_night = VALUES(wind_scale_night),
            wind_speed_night = VALUES(wind_speed_night), precip = VALUES(precip), uv_index = VALUES(uv_index),
            humidity = VALUES(humidity), pressure = VALUES(pressure), vis = VALUES(vis),
            cloud = VALUES(cloud), update_time = VALUES(update_time)
        """
        try:
            cursor.execute(insert_query, values)
            print(f"{city} {fx_date} 数据写入/更新成功: {day.get('textDay')}, 影响行数: {cursor.rowcount}")
            conn.commit()
            print(f"{city} 事务提交完成。")
        except mysql.connector.Error as e:
            print(f"{city} {fx_date} 数据库错误: {e}")
            conn.rollback()
            print(f"{city} 事务回滚。")
 #更新天气的函数
def update_weather(force_update=False):
    conn = connect_db()
    cursor = conn.cursor()

    for city, location in city_codes.items():
        latest_time = get_latest_update_time(cursor, city)
        if should_update_data(latest_time, force_update):
            print(f"开始更新 {city} 天气数据...")
            data = fetch_weather_data(city, location)
            if data:
                store_weather_data(conn, cursor, city, data)
        else:
            print(f"{city} 数据已为最新，无需更新。最新更新时间: {latest_time}")

    cursor.close()
    conn.close()


# 定期更新数据
def setup_scheduler():
    # # 在20秒后出发
    # now = datetime.now()
    # trigger_time = (now + timedelta(seconds=20)).strftime("%H:%M:%S")
    #
    # print(f"[测试日志] 当前时间: {now}")
    # print(f"[测试日志] 设置任务在 {trigger_time} 触发 update_weather")
    #
    # # 使用 lambda 延迟执行
    # schedule.every().day.at(trigger_time).do(update_weather)

    # # # 北京时间 1:00 对应 PDT 前一天的 16:00（夏令时）
    schedule.every().day.at("18:01").do(update_weather)

    while True:
        schedule.run_pending()
        time.sleep(60)

# if __name__ == '__main__':
#     conn = connect_db()
#     print(conn.is_connected())
#     print("数据库连接成功！")
#     conn.close()

# if __name__ == "__main__":
#     weather_data = fetch_weather_data("深圳宝安", city_codes["深圳宝安"])
#     print(weather_data)
#     print("解析成功！")

# if __name__ == '__main__':
#     # 测试 get_latest_update_time：从数据库读取每个城市最新的更新时间
#     conn = connect_db()
#     cursor = conn.cursor()
#     latest_time = get_latest_update_time(cursor, "深圳宝安")
#     need_update = should_update_data(latest_time)
#     print(latest_time)
#     print(need_update)
#     cursor.close()
#     conn.close()

# if __name__ == "__main__":
#     conn = connect_db()
#     cursor = conn.cursor()
#     data = fetch_weather_data("深圳宝安", "101280605")
#     store_weather_data(conn, cursor, "深圳宝安", data)
#     print("数据存储完成。")

# if __name__ == "__main__":
#     update_weather(force_update=False)

if __name__ == '__main__':
    setup_scheduler()
