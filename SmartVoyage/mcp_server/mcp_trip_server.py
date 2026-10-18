import json  # JSON 处理
from datetime import date, datetime, timedelta  # 时间处理
from decimal import Decimal  # 高精度小数类型
import requests  # HTTP 请求，用于调用 Qwen Embedding API

import mysql.connector  # MySQL 数据库驱动
from pymilvus import connections, Collection  # Milvus 向量数据库客户端

# from python_a2a import FastMCP, create_fastapi_app  # MCP 框架：FastMCP 用于定义工具，create_fastapi_app 转为 FastAPI 服务
# import uvicorn  # ASGI 服务器，用于运行 FastAPI 应用
from mcp.server.fastmcp import FastMCP

from SmartVoyage.config import Config  # 项目配置
from SmartVoyage.create_logger import logger  # 日志模块
from SmartVoyage.utils.format import DateEncoder, default_encoder  # 日期格式化工具

conf = Config()

# 定义普通方法
def get_embedding(text: str) -> list:
    """调用 Qwen Embedding API 生成文本向量"""
    import requests
    headers = {
        "Authorization": f"Bearer {conf.api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": conf.embedding_model,
        "input": [text],
        "dimensions": conf.embedding_dim
    }
    response = requests.post(conf.embedding_url, headers=headers, json=payload, timeout=30)
    return response.json()["data"][0]["embedding"]

def search_tour_groups_in_milvus(query_text: str, city: str = None, limit: int = 5) -> list:
    """在 Milvus 中进行语义搜索，找到最匹配的旅游团"""
    from pymilvus import connections, Collection
    connections.connect(alias="default", host=conf.milvus_host, port=conf.milvus_port)
    collection = Collection(conf.tour_group_collection)
    collection.load()

    results = collection.search(
        data=[get_embedding(query_text)],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 10}},
        limit=limit,
        output_fields=["tour_id", "tour_name", "city", "days", "price",
                       "total_seats", "remaining_seats", "agency", "rating",
                       "departure_dates", "highlights"],
        expr=f'city == "{city}"' if city else None  #muvils 中进行元数据过滤
    )

    tour_list = []
    for hits in results:
        for hit in hits:
            tour_list.append({
                "tour_id": hit.entity.get("tour_id"),
                "tour_name": hit.entity.get("tour_name"),
                "city": hit.entity.get("city"),
                "days": hit.entity.get("days"),
                "price": hit.entity.get("price"),
                "similarity": round(hit.distance, 4),
            })
    return tour_list


class TripService:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=conf.host, user=conf.user,
            password=conf.password, database=conf.database
        )

    def _execute_query(self, sql: str, params: list = None) -> str:
        """
        执行 SQL 查询，返回 JSON 格式的结果

        参数：
            sql (str): SQL 查询语句，使用 %s 占位符
            params (list): SQL 参数列表

        返回值：
            str: JSON 字符串
        """
        try:
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql, params or [])
            results = cursor.fetchall()
            cursor.close()

            # 处理特殊类型（日期、Decimal 等）
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)

            if results:
                response = {"status": "success", "data": results}
            else:
                response = {"status": "no_data", "message": "未找到行程数据，请确认查询条件。"}

            return json.dumps(response, cls=DateEncoder, ensure_ascii=False)

        except Exception as e:
            logger.error(f"行程查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # ========== 租车查询（MySQL） ==========

    def query_car_rental(self, pickup_city: str, return_city: str, date: str, car_type: str = None) -> str:
        """
        查询租车信息（从 MySQL car_rentals 表查询）
        """
        logger.info(f"查询租车: {pickup_city} -> {return_city}, {date}, {car_type}")
        sql = ("SELECT id, company, pickup_city, return_city, pickup_date, car_type, "
               "car_model, price_per_day, total_available, transmission, seats, deposit "
               "FROM car_rentals "
               "WHERE pickup_city = %s AND return_city = %s AND pickup_date = %s")
        params = [pickup_city, return_city, date]
        if car_type:
            sql += " AND car_type = %s"
            params.append(car_type)
        return self._execute_query(sql, params)

    # ========== 旅游团查询（Milvus RAG） ==========

    def query_tour_group(self, query_text: str, city: str = None) -> str:
        """
        查询旅游团信息（从 Milvus 向量数据库进行语义检索）

        参数：
            query_text (str): 用户查询描述，如"想看雪山的地方"、"适合亲子游的短途旅行"
            city (str, optional): 城市过滤条件

        返回值：
            str: JSON 字符串，包含匹配的旅游团列表
        """
        logger.info(f"查询旅游团: query='{query_text}', city='{city}'")
        try:
            tour_list = search_tour_groups_in_milvus(query_text, city, limit=5)

            if tour_list:
                return json.dumps({"status": "success", "data": tour_list}, ensure_ascii=False)
            else:
                return json.dumps({
                    "status": "no_data",
                    "message": f"未找到匹配的旅游团。{'请确认城市名称，' if city else ''}或尝试其他搜索条件。"
                }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"旅游团 RAG 查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": f"旅游团查询出错：{str(e)}"}, ensure_ascii=False)

    # ========== 保险查询（MySQL） ==========

    def query_insurance(self, insurance_type: str = None) -> str:
        """
        查询旅行保险产品信息（从 MySQL insurances 表查询）
        """
        logger.info(f"查询保险: {insurance_type}")
        sql = ("SELECT id, insurance_type, name, company, coverage, price, "
               "duration_days, max_coverage, medical_coverage, baggage_coverage, flight_delay "
               "FROM insurances")
        params = []
        if insurance_type:
            sql += " WHERE insurance_type = %s"
            params.append(insurance_type)
        return self._execute_query(sql, params)

    # ========== 三个预订方法 ==========

    def order_car_rental(self, date: str, car_type: str, number: int) -> str:
        """预订租车"""
        logger.info(f"预订租车: {date}, {car_type}, {number}辆")
        return f"恭喜，租车预订成功！日期：{date}，车型：{car_type}，数量：{number}辆。"

    def order_tour_group(self, date: str, tour_name: str, number: int) -> str:
        """报名旅游团"""
        logger.info(f"报名旅游团: {date}, {tour_name}, {number}人")
        return f"恭喜，旅游团报名成功！团名：{tour_name}，日期：{date}，人数：{number}人。"

    def order_insurance(self, insurance_type: str, date: str, number: int) -> str:
        """购买旅行保险"""
        logger.info(f"购买保险: {insurance_type}, {date}, {number}份")
        return f"恭喜，旅行保险购买成功！类型：{insurance_type}，日期：{date}，份数：{number}份。"

# ========== 注册查询工具 ==========
def create_trip_mcp_server():
    """
    创建并启动行程管家 MCP 服务器
    """
    # trip_mcp = FastMCP(name="TripTools")

    # 2) 端口写在构造里 —— 注意不是 run() 的参数
    trip_mcp = FastMCP(
        name="TripTools",
        instructions="行程工具，支持租车、旅游团、保险的查询与预订。",
        log_level="ERROR",
        host="127.0.0.1", port=8003,
    )

    service = TripService()

    @trip_mcp.tool(
        name="query_car_rental",
        description="查询租车信息，参数：pickup_city(取车城市), return_city(还车城市), date(日期，格式YYYY-MM-DD), car_type(车型类型，可选：经济型/SUV/豪华型/MPV)"
    )
    def query_car_rental(pickup_city: str, return_city: str, date: str, car_type: str = None) -> str:
        return service.query_car_rental(pickup_city, return_city, date, car_type)

    @trip_mcp.tool(
        name="query_tour_group",
        description="查询旅游团信息（语义搜索），参数：query_text(查询描述，如'想看雪山的地方')，city(城市过滤，可选)"
    )
    def query_tour_group(query_text: str, city: str = None) -> str:
        return service.query_tour_group(query_text, city)

    @trip_mcp.tool(
        name="query_insurance",
        description="查询旅行保险产品，参数：insurance_type(保险类型，可选：综合型/意外型/医疗型/境外型)"
    )
    def query_insurance(insurance_type: str = None) -> str:
        return service.query_insurance(insurance_type)

    # ========== 注册预订工具 ==========

    @trip_mcp.tool(
        name="order_car_rental",
        description="根据日期、车型和数量预订租车服务。参数：date(租车日期，格式YYYY-MM-DD), car_type(车型，如经济型/SUV/豪华型/MPV), number(租车数量)"
    )
    def order_car_rental(date: str, car_type: str, number: int) -> str:
        logger.info(f"正在预订租车: {date}, {car_type}, {number}辆")
        return service.order_car_rental(date, car_type, number)

    @trip_mcp.tool(
        name="order_tour_group",
        description="根据出发日期、旅游团名称和人数报名旅游团。参数：date(出发日期，格式YYYY-MM-DD), tour_name(旅游团名称，需与查询结果中的团名一致), number(报名人数)"
    )
    def order_tour_group(date: str, tour_name: str, number: int) -> str:
        logger.info(f"正在报名旅游团: {date}, {tour_name}, {number}人")
        return service.order_tour_group(date, tour_name, number)

    @trip_mcp.tool(
        name="order_insurance",
        description="根据保险类型、生效日期和份数购买旅行保险。参数：insurance_type(保险类型，如综合型/意外型/医疗型/境外型), date(生效日期，格式YYYY-MM-DD), number(购买份数)"
    )
    def order_insurance(insurance_type: str, date: str, number: int) -> str:
        logger.info(f"正在购买保险: {insurance_type}, {date}, {number}份")
        return service.order_insurance(insurance_type, date, number)

    # todo: 第4步：只返回装配好的对象，不在这里启动
    return trip_mcp

    # ===== 下面是修改前的写法，保留作对比，不要恢复 =====
    # 问题同 mcp_weather_server：uvicorn.run() 阻塞，函数永远不返回，
    #      test_trip_mcp_server_config 调用后直接卡死。
    #      另外 host="0.0.0.0" 是监听所有网卡，局域网内可访问，且这些工具没有认证。
    # app = create_fastapi_app(mcp_server=trip_mcp)
    # uvicorn.run(app, host="0.0.0.0", port=8003)


# todo: 第5步：启动单独抽成一个函数，副作用集中在这里
def run_trip_mcp_server(host: str = "127.0.0.1", port: int = 8003):
    # """启动行程 MCP 服务器（阻塞，Ctrl+C 退出）
    #
    # host 默认改成 127.0.0.1 只监听本机。需要局域网访问再显式传 "0.0.0.0"，
    # 注意这些工具没有任何认证，同网段的人都能直接下单。
    # """
    # trip_mcp = create_trip_mcp_server()
    # app = create_fastapi_app(mcp_server=trip_mcp)
    # print(f"服务器已启动，请访问 http://{host}:{port}/tools")
    # uvicorn.run(app, host=host, port=port)

    #标准的mcp库中的FastMCP
    trip_mcp = create_trip_mcp_server()
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8003/mcp")
        trip_mcp.run(transport="streamable-http") # 不再 create_fastapi_app + uvicorn
    except Exception as e:
        print(f"服务器启动失败: {e}")


if __name__ == '__main__':
    # 改为调用 run_*，create_* 只负责装配，测试里可以安全调用
    run_trip_mcp_server()

    # ===== 修改前：这里调的是 create_*，装配和启动分不开 =====
    # create_trip_mcp_server()