import json
import unittest
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))


class TestStockMCPIntegration(unittest.TestCase):
    """集成测试：股票分析 MCP 服务器"""

    @classmethod
    def setUpClass(cls):
        from mcp_server.mcp_stock_server import StockAnalysisService
        cls.service = StockAnalysisService()

    def test_get_stock_examples(self):
        """测试获取股票代码示例"""
        result = self.service.get_stock_examples()
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertIn("美股", parsed["data"])
        self.assertIn("AAPL", parsed["data"]["美股"])

    def test_search_stock_symbols(self):
        """测试搜索股票代码"""
        result = self.service.search_stock_symbols("苹果")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "success")
        self.assertGreater(len(parsed["data"]), 0)
        self.assertEqual(parsed["data"][0]["symbol"], "AAPL")

    def test_search_stock_symbols_no_result(self):
        """测试搜索不存在的股票"""
        result = self.service.search_stock_symbols("不存在的股票123")
        parsed = json.loads(result)
        self.assertEqual(parsed["status"], "no_data")

    def test_analyze_stock_price_daily(self):
        """测试日线分析"""
        result = self.service.analyze_stock_price("AAPL", "1d")
        parsed = json.loads(result)

        # 如果获取数据成功，验证返回结构
        if parsed["status"] == "success":
            self.assertEqual(parsed["symbol"], "AAPL")
            self.assertIn("current_price", parsed)
            self.assertIn("technical_indicators", parsed)
            self.assertIn("candlestick_patterns", parsed)
            self.assertIn("chart_patterns", parsed)
            print(f"\n当前价格: {parsed['current_price']}")
            print(f"涨跌幅: {parsed['change_percent']:.2f}%")
        else:
            print(f"\n警告: {parsed.get('message', '数据获取失败')}")

    def test_analyze_stock_price_hourly(self):
        """测试小时线分析"""
        result = self.service.analyze_stock_price("TSLA", "1h")
        parsed = json.loads(result)

        if parsed["status"] == "success":
            self.assertEqual(parsed["symbol"], "TSLA")
            self.assertIn("interval", parsed)
        else:
            print(f"\n警告: {parsed.get('message', '数据获取失败')}")

    def test_analyze_multiple_intervals(self):
        """测试多周期分析"""
        result = self.service.analyze_stock_multiple_intervals("AAPL")
        parsed = json.loads(result)

        if parsed["status"] == "success":
            self.assertEqual(parsed["symbol"], "AAPL")
            self.assertIn("intervals", parsed)
            print(f"\n成功分析 {len(parsed['intervals'])} 个周期")

            for interval_data in parsed["intervals"]:
                print(f"- {interval_data['interval_name']}: 价格 {interval_data['data']['current_price']:.2f}")
        else:
            print(f"\n警告: {parsed.get('message', '数据获取失败')}")

    def test_stock_mcp_server_config(self):
        """验证股票分析 MCP 服务器配置"""
        from mcp_server.mcp_stock_server import create_stock_mcp_server
        server = create_stock_mcp_server()
        self.assertEqual(server.name, "StockAnalysisTools")


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)


"""
测试命令:

# 运行所有测试
python -m unittest SmartVoyage.tests.test_stock_mcp -v

# 运行单个测试
python -m unittest SmartVoyage.tests.test_stock_mcp.TestStockMCPIntegration.test_analyze_stock_price_daily -v

# 直接运行文件
python SmartVoyage/tests/test_stock_mcp.py
"""
