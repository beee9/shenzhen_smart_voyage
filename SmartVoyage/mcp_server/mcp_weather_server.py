import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger
from SmartVoyage.utils.format import DateEncoder, default_encoder

conf = Config()
#现有普通类和普通方法
# 天气服务类
class WeatherService:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    # 执行参数化查询，返回JSON字符串
    def query_weather(self, city: str, start_date: str, end_date: str) -> str:
        try:
            cursor = self.conn.cursor(dictionary=True)
            sql = ("SELECT city, fx_date, temp_max, temp_min, text_day, text_night, "
                   "humidity, wind_dir_day, wind_scale_day, precip FROM weather_data "
                   "WHERE city = %s AND fx_date BETWEEN %s AND %s ORDER BY fx_date")
            cursor.execute(sql, [city, start_date, end_date])
            results = cursor.fetchall()
            cursor.close()
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)  #default_encoder 专门用来处理mysql的特殊字段
            return json.dumps(
                {"status": "success", "data": results} if results
                else {"status": "no_data", "message": "未找到天气数据，请确认城市和日期。"},
                cls=DateEncoder, ensure_ascii=False
            )
        except Exception as e:
            logger.error(f"天气查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

import requests

def fetch_weather_from_api(city: str, start_date: str, end_date: str) -> str:
    """从和风天气 API 获取天气数据"""
    logger.info(f"从和风天气API获取数据: {city}, {start_date} ~ {end_date}")

    # todo: 第1步：城市名转 location id（geo 接口）
    # 注意 URL 用 conf.qweather_host（每个 key 有专属 API Host），
    # 且路径带 /geo 前缀。旧的公共域名 geoapi.qweather.com 已下线，一律 404
    geo_url = (f"https://{conf.qweather_host}/geo/v2/city/lookup"
               f"?location={city}&key={conf.qweather_api_key}")
    geo_resp = requests.get(geo_url, timeout=15)

    # todo: 第2步：先查 HTTP 状态码，再 .json()
    # 404 时 body 是空字符串，直接 .json() 会抛 JSONDecodeError，
    # 报错完全看不出是接口不通，排查时很费时间
    if geo_resp.status_code == 400:
        # 400 是"城市名无法识别"这类业务错误，不是配置问题，归到 no_data
        return json.dumps({"status": "no_data", "message": f"未找到城市：{city}"}, ensure_ascii=False)
    if geo_resp.status_code != 200:
        # 404 多半是 qweather_host 写错或用了已下线的公共域名，
        # 401/403 是 key 无效，402 是超额 —— 这些是配置/账号问题，要区别于 no_data
        msg = f"和风天气 geo 接口返回 HTTP {geo_resp.status_code}，请检查 qweather_host 与 key 配置"
        logger.error(msg)
        return json.dumps({"status": "error", "message": msg}, ensure_ascii=False)

    geo_data = geo_resp.json()
    if not geo_data.get("location"):
        # code 非 200 时也走这里，把 code 一并带上便于定位（如 401 key 无效、402 超额）
        return json.dumps(
            {"status": "no_data",
             "message": f"未找到城市：{city}（和风返回 code={geo_data.get('code')}）"},
            ensure_ascii=False
        )

    location_id = geo_data["location"][0]["id"]

    # todo: 第3步：拿 location id 查 7 天预报，同样先判状态码
    weather_url = (f"https://{conf.qweather_host}/v7/weather/7d"
                   f"?location={location_id}&key={conf.qweather_api_key}")
    weather_resp = requests.get(weather_url, timeout=15)
    if weather_resp.status_code != 200:
        msg = f"和风天气预报接口返回 HTTP {weather_resp.status_code}"
        logger.error(msg)
        return json.dumps({"status": "error", "message": msg}, ensure_ascii=False)

    weather_data = weather_resp.json()

    # todo: 第4步：按日期区间过滤
    # 注意 7d 接口只返回"今天起未来 7 天"，查历史日期或更远的未来一定是空，
    # 这是 API 数据源和数据库数据源最大的区别（数据库里能存任意日期）
    results = []
    for day in weather_data.get("daily", []):
        if start_date <= day.get("fxDate", "") <= end_date:
            results.append({
                "city": city,
                "fx_date": day.get("fxDate"),
                "temp_max": int(day.get("tempMax", 0)),
                "temp_min": int(day.get("tempMin", 0)),
                "text_day": day.get("textDay", ""),
                "text_night": day.get("textNight", ""),
                "humidity": int(day.get("humidity", 0)),
                "wind_dir_day": day.get("windDirDay", ""),
                "wind_scale_day": day.get("windScaleDay", ""),
                "precip": float(day.get("precip", 0))
            })

    if results:
        return json.dumps({"status": "success", "data": results}, ensure_ascii=False)
    return json.dumps({"status": "no_data", "message": "未找到天气数据。"}, ensure_ascii=False)


def create_weather_mcp_server():
    weather_mcp = FastMCP(
        name="WeatherTools",
        instructions="天气查询工具，支持数据库或和风天气API双数据源。",
        log_level="ERROR",
        host="127.0.0.1", port=8002
    )

    service = WeatherService()

    @weather_mcp.tool(
        name="query_weather",
        description="查询天气数据，参数：city(城市), start_date(开始日期YYYY-MM-DD), end_date(结束日期YYYY-MM-DD)"
    )
    def query_weather(city: str, start_date: str, end_date: str) -> str:
        logger.info(f"执行天气查询: {city}, {start_date} ~ {end_date}")
        if conf.weather_source == "api":
            return fetch_weather_from_api(city, start_date, end_date)
        return service.query_weather(city, start_date, end_date)

    logger.info("=== 天气MCP服务器信息 ===")
    logger.info(f"名称: {weather_mcp.name}")
    logger.info(f"描述: {weather_mcp.instructions}")

    # todo: 第4步：只返回装配好的对象，不在这里启动
    return weather_mcp

    # ===== 下面是修改前的写法，保留作对比，不要恢复 =====
    # 问题：装配和启动混在一个函数里，run() 是阻塞调用，函数永远不返回，
    #      也就没有 return，调用方拿到的是 None。
    #      导致 test_weather_mcp_server_config 一调用就卡死在这里，
    #      后面的 assertEqual(server.name, ...) 永远执行不到。
    # try:
    #     print("服务器已启动，请访问 http://127.0.0.1:8002/mcp")
    #     weather_mcp.run(transport="streamable-http")
    # except Exception as e:
    #     print(f"服务器启动失败: {e}")


# todo: 第5步：启动单独抽成一个函数，副作用集中在这里
def run_weather_mcp_server():
    """启动天气 MCP 服务器（阻塞，Ctrl+C 退出）"""
    weather_mcp = create_weather_mcp_server()
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8002/mcp")
        weather_mcp.run(transport="streamable-http")
    except Exception as e:
        print(f"服务器启动失败: {e}")


# if __name__ == '__main__':
#     # weatherService =WeatherService()
#     # result = weatherService.query_weather("深圳宝安","2026-08-20","2026-08-20")
#     # print(result)
#
#     result=fetch_weather_from_api("深圳宝安","2026-08-20","2026-08-20")
#     print(result)

if __name__ == '__main__':
    # 改为调用 run_*，create_* 只负责装配，测试里可以安全调用
    run_weather_mcp_server()

    # ===== 修改前：这里调的是 create_*，装配和启动分不开 =====
    # create_weather_mcp_server()
