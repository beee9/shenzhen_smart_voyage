import unittest
import json
from datetime import date, datetime, timedelta
from decimal import Decimal

from SmartVoyage.utils.format import default_encoder, DateEncoder

class TestFormatEncoder(unittest.TestCase):
    """测试 default_encoder 函数和 DateEncoder 类"""
    #测试某个测试用例时候的一个前置操作
    def setUp(self):
        from SmartVoyage.utils.format import default_encoder, DateEncoder
        self.default_encoder_func = default_encoder
        self.date_encoder_cls = DateEncoder

    def test_encode_datetime(self):
        """测试 datetime 编码"""
        dt = datetime(2025, 7, 30, 14, 30, 0)
        result = self.default_encoder_func(dt)
        self.assertEqual(result, '2025-07-30 14:30:00')

    def test_encode_date(self):
        """测试 date 编码"""
        d = date(2025, 7, 30)
        result = self.default_encoder_func(d)
        self.assertEqual(result, '2025-07-30')

    def test_encode_timedelta(self):
        """测试 timedelta 编码"""
        td = timedelta(hours=5, minutes=30)
        result = self.default_encoder_func(td)
        self.assertEqual(result, '5:30:00')

    def test_encode_decimal(self):
        """测试 Decimal 编码"""
        dec = Decimal('123.45')
        result = self.default_encoder_func(dec)
        self.assertIsInstance(result, float)
        self.assertAlmostEqual(result, 123.45)

    def test_encode_unknown(self):
        """测试未知类型原样返回"""
        obj = "hello"
        result = self.default_encoder_func(obj)
        self.assertEqual(result, "hello")

    def test_date_encoder_json_dumps(self):
        """测试 DateEncoder 类与 json.dumps 配合使用"""
        data = {
            "date": date(2025, 7, 30),
            "datetime": datetime(2025, 7, 30, 14, 30, 0),
            "value": Decimal('99.99')
        }
        result = json.dumps(data, cls=self.date_encoder_cls)
        parsed = json.loads(result)
        self.assertEqual(parsed["date"], "2025-07-30")
        self.assertEqual(parsed["datetime"], "2025-07-30 14:30:00")
        self.assertEqual(parsed["value"], 99.99)