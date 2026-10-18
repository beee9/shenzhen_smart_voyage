import json
import unittest


class TestWeatherMCPIntegration(unittest.TestCase):
    """集成测试：天气 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_weather_server import WeatherService
        cls.service = WeatherService()

    def test_query_weather_single_day(self):
        """测试单天天气查询"""
        # todo: 第1步：query_weather(city, start_date, end_date) 要 3 个参数，
        #       查单天要把日期写两遍，形成一个左右都闭合的区间
        result = self.service.query_weather("成都", "2026-05-01", "2026-05-01")

        # ===== 修改前：少传 end_date，直接 TypeError（ERROR 而非 FAIL）=====
        # TypeError: WeatherService.query_weather() missing 1 required
        #            positional argument: 'end_date'
        # result = self.service.query_weather("北京", "2025-07-30")

        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        first = parsed["data"][0]
        #first["city"] 为啥这个能取出来成都,是因为我们的接口定义好了,返回值这里通过city就能取到城市
        self.assertEqual(first["city"], "成都")
        self.assertEqual(first["fx_date"], "2026-05-01")

    def test_query_weather_no_data(self):
        """测试无数据情况"""
        # todo: 第2步：同样补上 end_date。"火星"库里必然没有，用来测 no_data 分支
        result = self.service.query_weather("火星", "2025-07-30", "2025-07-30")

        # ===== 修改前：同样少传 end_date =====
        # result = self.service.query_weather("火星", "2025-07-30")

        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_weather_mcp_server_config(self):
        """验证天气 MCP 服务器配置"""
        from SmartVoyage.mcp_server.mcp_weather_server import create_weather_mcp_server
        server = create_weather_mcp_server()
        self.assertEqual(server.name, "WeatherTools")
# select * from train_tickets tt  limit 10;
class TestTicketMCPIntegration(unittest.TestCase):
    """集成测试：票务 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_ticket_server import TicketService
        cls.service = TicketService()

    def test_query_train(self):
        """测试火车票查询"""
        result = self.service.query_train("北京", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)

    def test_query_train_with_seat(self):
        """测试带座位类型的火车票查询"""
        result = self.service.query_train("北京", "成都", "2026-05-01", "二等座")
        parsed = json.loads(result)

        # todo: 第3步：no_data 分支的返回里没有 data 键，直接取会 KeyError。
        #       先断言 status，让失败信息落在"查不到数据"这个真正的原因上
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["seat_type"], "二等座")

        # ===== 修改前：不先断言 status 就取 parsed["data"] =====
        # 返回 {"status": "no_data", "message": ...} 时没有 data 键，
        # 报 KeyError: 'data'（ERROR），掩盖了"库里没数据"这个真实原因。
        # for item in parsed["data"]:
        #     self.assertEqual(item["seat_type"], "二等座")
#select * from flight_tickets ft  limit 10;
    def test_query_flight(self):
        """测试机票查询"""
        result = self.service.query_flight("北京", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")

    def test_query_flight_with_cabin(self):
        """测试带舱位类型的机票查询（覆盖 cabin_type 可选参数分支）"""
        # todo: 第4步：cabin_type 不传时 SQL 少一个 AND 条件，
        #       传了才会走 "AND cabin_type = %s" 那条分支，两条路都要测
        result = self.service.query_flight("北京", "成都", "2026-05-01", "经济舱")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["cabin_type"], "经济舱")

    def test_query_concert_with_ticket_type(self):
        """测试带票种的演唱会票查询（覆盖 ticket_type 可选参数分支）"""
        result = self.service.query_concert("成都", "薛之谦", "2026-05-01", "VIP内场")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["ticket_type"], "VIP内场")
# select * from concert_tickets ct  limit 10;
    def test_query_concert(self):
        """测试演唱会票查询"""
        result = self.service.query_concert("成都", "薛之谦", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        first = parsed["data"][0]
        self.assertEqual(first["artist"], "薛之谦")

class TestTripMCPIntegration(unittest.TestCase):
    """集成测试：行程 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from SmartVoyage.mcp_server.mcp_trip_server import TripService
        cls.service = TripService()
# select * from car_rentals cr limit 10;
    def test_query_car_rental(self):
        """测试租车查询"""
        result = self.service.query_car_rental("成都", "成都", "2026-05-01")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")

    def test_query_car_rental_with_car_type(self):
        """测试带车型的租车查询（覆盖 car_type 可选参数分支）"""
        result = self.service.query_car_rental("成都", "成都", "2026-05-01", "经济型")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["car_type"], "经济型")

    # ========== 旅游团查询：唯一走 Milvus 向量检索的链路 ==========

    def test_query_tour_group(self):
        """测试旅游团语义搜索（Milvus 向量检索 + embedding API）"""
        # todo: 第5步：这条链路和其他查询完全不同——先调 embedding API 把
        #       query_text 转成向量，再去 Milvus 做 COSINE 相似度检索。
        #       依赖 Milvus 服务开着，且会消耗真实的 embedding API 额度。
        result = self.service.query_tour_group("想看雪山的地方")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)

        # 语义搜索的结果带 similarity 分值，这是它和 SQL 查询最直观的区别
        first = parsed["data"][0]
        self.assertIn("similarity", first)
        self.assertIn("tour_name", first)

    def test_query_tour_group_with_city(self):
        """测试带城市过滤的旅游团搜索（覆盖 Milvus expr 过滤分支）"""
        # city 传了会生成 expr='city == "成都"'，是标量过滤 + 向量检索的组合
        result = self.service.query_tour_group("云南丽江大理双飞6日游", "丽江")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            print("================")
            print(item)
            print("================")
            self.assertEqual(item["city"], "丽江")

# select * from insurances i  limit 10;
    def test_query_insurance_with_type(self):
        """测试带类型的保险查询"""
        result = self.service.query_insurance("综合型")
        parsed = json.loads(result)
        # todo: 第6步：和 test_query_train_with_seat 同一个坑——先断言 status，
        #       否则 no_data 时 parsed["data"] 会 KeyError
        self.assertEqual(parsed["status"], "success")
        for item in parsed["data"]:
            self.assertEqual(item["insurance_type"], "综合型")

    def test_query_insurance_no_type(self):
        """测试不带类型的保险查询（覆盖默认分支，返回全部类型）"""
        result = self.service.query_insurance()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        # 不过滤时应该拿到多种保险类型
        types = {item["insurance_type"] for item in parsed["data"]}
        self.assertGreater(len(types), 1)

    def test_trip_mcp_server_config(self):
        """验证行程 MCP 服务器配置"""
        from SmartVoyage.mcp_server.mcp_trip_server import create_trip_mcp_server
        server = create_trip_mcp_server()
        self.assertEqual(server.name, "TripTools")

#测试方法:
'''
# $env:PYTHONPATH = "."
# 运行整个测试模块
python -m  unittest SmartVoyage.tests.test_mcp_servers_02 -v

# 运行单个测试类
#测试天气MCP
python -m unittest SmartVoyage.tests.test_mcp_servers.TestWeatherMCPIntegration -v

#测试票务MCP

python -m unittest SmartVoyage.tests.test_mcp_servers.TestTicketMCPIntegration -v

#测试行程MCP
python -m unittest SmartVoyage.tests.test_mcp_servers.TestTripMCPIntegration -v




# 运行单个测试方法 例如查天气MCP的test_query_weather_single_day 测试
python -m unittest SmartVoyage.tests.test_mcp_servers.TestWeatherMCPIntegration.test_query_weather_single_day -v
python -m unittest SmartVoyage.tests.test_mcp_servers.TestTripMCPIntegration.test_query_tour_group_with_city -v
python -m unittest SmartVoyage.tests.test_mcp_servers.TestTripMCPIntegration.test_query_tour_group -v
'''