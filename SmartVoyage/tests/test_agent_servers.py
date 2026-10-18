import unittest


class TestWeatherAgentIntegration(unittest.TestCase):
    """集成测试：天气 Agent 服务器"""

    def test_handle_task_weather_query(self):
        """测试天气 Agent 完整查询流程"""
        import asyncio
        from SmartVoyage.a2a_server.weather_server import  query_weather

        result = asyncio.run(query_weather("成都 2026-08-13 天气"))
        print(result)
        self.assertEqual(result["status"], "success")
        self.assertIn("成都", result["message"])

    def test_weather_server_instance(self):
        """验证天气服务器实例化"""
        from SmartVoyage.a2a_server.weather_server import WeatherQueryServer
        server = WeatherQueryServer()
        self.assertEqual(server.agent_card.name, "WeatherQueryAssistant")

class TestTicketAgentIntegration(unittest.TestCase):
    """集成测试：票务 Agent 服务器"""

    def test_handle_task_ticket_query(self):
        """测试票务 Agent 完整查询流程"""
        import asyncio
        from SmartVoyage.a2a_server.ticket_server import query_tickets

        result = asyncio.run(query_tickets("北京 到 成都 火车票 2026-05-05"))
        self.assertEqual(result["status"], "success")
        self.assertIn("北京", result["message"])
        self.assertIn("成都", result["message"])

class TestTripAgentIntegration(unittest.TestCase):
    """集成测试：行程 Agent 服务器"""

    def test_handle_task_trip_query(self):
        """测试行程 Agent 完整查询流程"""
        import asyncio
        from SmartVoyage.a2a_server.trip_server import query_trip

        # result = asyncio.run(query_trip("北京租车 2025-08-01"))
        # self.assertEqual(result["status"], "success")
        # self.assertIn("北京", result["message"])

        result = asyncio.run(query_trip("丽江 适合亲子游的短途旅行 2025-08-01-2026年9月30日随便一天都行"))
        self.assertEqual(result["status"], "success")
        self.assertIn("丽江", result["message"])
        self.assertIn("北京", result["message"]) #这是是失败的测试用例

#测试方法
'''
# $env:PYTHONPATH = "."
# 运行整个测试模块
python -m  unittest SmartVoyage.tests.test_agent_servers -v

# 运行单个测试类
#测试天气MCP
python -m unittest SmartVoyage.tests.test_agent_servers.TestWeatherAgentIntegration -v

#测试票务MCP

python -m unittest SmartVoyage.tests.test_agent_servers.TestTicketAgentIntegration -v

#测试行程MCP
python -m unittest SmartVoyage.tests.test_mcp_servers.TestTripAgentIntegration -v




# 运行单个测试方法 例如TestTripAgentIntegration的test_handle_task_trip_query 测试
python -m unittest SmartVoyage.tests.test_mcp_servers.TestWeatherMCPIntegration.test_handle_task_trip_query -v
'''