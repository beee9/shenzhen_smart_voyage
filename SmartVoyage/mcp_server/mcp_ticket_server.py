import mysql.connector
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from mcp.server.fastmcp import FastMCP

from SmartVoyage.config import Config
from SmartVoyage.create_logger import logger
from SmartVoyage.utils.format import DateEncoder, default_encoder

conf = Config()

# 票务服务类
class TicketService:
    def __init__(self):
        self.conn = mysql.connector.connect(
            host=conf.host,
            user=conf.user,
            password=conf.password,
            database=conf.database
        )

    # 执行参数化查询，返回JSON字符串
    def _execute_query(self, sql: str, params: list = None) -> str:
        try:
            cursor = self.conn.cursor(dictionary=True)
            cursor.execute(sql, params or [])
            results = cursor.fetchall()
            cursor.close()
            for result in results:
                for key, value in result.items():
                    if isinstance(value, (date, datetime, timedelta, Decimal)):
                        result[key] = default_encoder(value)
            return json.dumps(
                {"status": "success", "data": results} if results
                else {"status": "no_data", "message": "未找到票务数据，请确认查询条件。"},
                cls=DateEncoder, ensure_ascii=False
            )
        except Exception as e:
            logger.error(f"票务查询错误: {str(e)}")
            return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

    # 查询火车票（参数化）
    def query_train(self, departure_city: str, arrival_city: str, date: str, seat_type: str = None) -> str:
        sql = ("SELECT id, departure_city, arrival_city, departure_time, arrival_time, "
               "train_number, seat_type, price, remaining_seats FROM train_tickets "
               "WHERE departure_city = %s AND arrival_city = %s AND DATE(departure_time) = %s")
        params = [departure_city, arrival_city, date]
        if seat_type:
            sql += " AND seat_type = %s"
            params.append(seat_type)
        return self._execute_query(sql, params)

    # 查询机票（参数化）
    def query_flight(self, departure_city: str, arrival_city: str, date: str, cabin_type: str = None) -> str:
        sql = ("SELECT id, departure_city, arrival_city, departure_time, arrival_time, "
               "flight_number, cabin_type, price, remaining_seats FROM flight_tickets "
               "WHERE departure_city = %s AND arrival_city = %s AND DATE(departure_time) = %s")
        params = [departure_city, arrival_city, date]
        if cabin_type:
            sql += " AND cabin_type = %s"
            params.append(cabin_type)
        return self._execute_query(sql, params)

    # 查询演唱会票（参数化）
    def query_concert(self, city: str, artist: str, date: str, ticket_type: str = None) -> str:
        sql = ("SELECT id, artist, city, venue, start_time, end_time, "
               "ticket_type, price, remaining_seats FROM concert_tickets "
               "WHERE city = %s AND artist = %s AND DATE(start_time) = %s")
        params = [city, artist, date]
        if ticket_type:
            sql += " AND ticket_type = %s"
            params.append(ticket_type)
        return self._execute_query(sql, params)

    # 预定方法（模拟返回）
    def order_train(self, departure_date: str, train_number: str, seat_type: str, number: int) -> str:
        return f"恭喜，火车票预定成功！日期：{departure_date}，车次：{train_number}，座位：{seat_type}，数量：{number}张。"

    def order_flight(self, departure_date: str, flight_number: str, cabin_type: str, number: int) -> str:
        return f"恭喜，机票预定成功！日期：{departure_date}，航班号：{flight_number}，舱位：{cabin_type}，数量：{number}张。"

    def order_concert(self, start_date: str, artist: str, venue: str, ticket_type: str, number: int) -> str:
        return f"恭喜，演出票预定成功！日期：{start_date}，艺人：{artist}，场馆：{venue}，票类型：{ticket_type}，数量：{number}张。"


# 创建mcp server 对象
def create_ticket_mcp_server():
    ticket_mcp = FastMCP(
        name="TicketTools",
        instructions="票务工具，支持火车票、机票、演唱会票的查询与预定。",
        log_level="ERROR",
        host="127.0.0.1", port=8001
    )
    #实际提供服务 实例化一下, 就创建mysql的连接对象
    service = TicketService()

    # 注册查询工具
    @ticket_mcp.tool(
        name="query_train",
        description="查询火车票信息，参数：departure_city(出发城市), arrival_city(到达城市), date(日期), seat_type(座位类型，可选)"
    )
    def query_train(departure_city: str, arrival_city: str, date: str, seat_type: str = None) -> str:
        return service.query_train(departure_city, arrival_city, date, seat_type)

    @ticket_mcp.tool(
        name="query_flight",
        description="查询机票信息，参数：departure_city(出发城市), arrival_city(到达城市), date(日期), cabin_type(舱位类型，可选)"
    )
    def query_flight(departure_city: str, arrival_city: str, date: str, cabin_type: str = None) -> str:
        return service.query_flight(departure_city, arrival_city, date, cabin_type)

    @ticket_mcp.tool(
        name="query_concert",
        description="查询演唱会票信息，参数：city(城市), artist(艺人), date(日期), ticket_type(票类型，可选)"
    )
    def query_concert(city: str, artist: str, date: str, ticket_type: str = None) -> str:
        return service.query_concert(city, artist, date, ticket_type)

    # 注册预定工具
    @ticket_mcp.tool(
        name="order_train",
        description="根据日期、车次、座位类型、数量预定火车票"
    )
    def order_train(departure_date: str, train_number: str, seat_type: str, number: int) -> str:
        return service.order_train(departure_date, train_number, seat_type, number)

    @ticket_mcp.tool(
        name="order_flight",
        description="根据日期、航班号、舱位类型、数量预定机票"
    )
    def order_flight(departure_date: str, flight_number: str, cabin_type: str, number: int) -> str:
        return service.order_flight(departure_date, flight_number, cabin_type, number)

    @ticket_mcp.tool(
        name="order_concert",
        description="根据日期、艺人、场馆、票类型、数量预定演出票"
    )
    def order_concert(start_date: str, artist: str, venue: str, ticket_type: str, number: int) -> str:
        return service.order_concert(start_date, artist, venue, ticket_type, number)

    logger.info("=== 票务MCP服务器信息 ===")
    logger.info(f"名称: {ticket_mcp.name}")
    logger.info(f"描述: {ticket_mcp.instructions}")

    # todo: 第4步：只返回装配好的对象，不在这里启动
    return ticket_mcp

    # ===== 下面是修改前的写法，保留作对比，不要恢复 =====
    # 问题同 mcp_weather_server：run() 阻塞，函数永远不返回，也就没有 return。
    # try:
    #     print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
    #     ticket_mcp.run(transport="streamable-http")
    # except Exception as e:
    #     print(f"服务器启动失败: {e}")


# todo: 第5步：启动单独抽成一个函数，副作用集中在这里
def run_ticket_mcp_server():
    """启动票务 MCP 服务器（阻塞，Ctrl+C 退出）"""
    ticket_mcp = create_ticket_mcp_server()
    try:
        print("服务器已启动，请访问 http://127.0.0.1:8001/mcp")
        ticket_mcp.run(transport="streamable-http")
    except Exception as e:
        print(f"服务器启动失败: {e}")

if __name__ == '__main__':
    run_ticket_mcp_server()


