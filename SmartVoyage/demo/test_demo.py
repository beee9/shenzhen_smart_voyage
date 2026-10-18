import unittest

#这里是为了测试临时加的一个Service
class SomeService:
    def __init__(self):
        print("SomeService 初始化了")
#测试类要继承unittest.TestCase
class TestExample1(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """类级别初始化，只执行一次"""
        cls.service = SomeService()

    def setUp(self):
        """每个测试方法运行前执行"""
        print("每次执行测试前:我先执行,我是每次执行测试的前置动作")
    # 我们的第一个测试用了 .每一个测试用例是以test_ 开头的
    def test_something1(self):
        self.assertEqual(1 + 1, 2)       # 相等断言
        self.assertTrue(True)             # 布尔断言
        self.assertGreater(5, 3)          # 大小断言
        self.assertIn("a", ["a", "b"])    # 包含断言

    def test_something2(self):
        self.assertEqual(1 + 1, 2)       # 相等断言
        self.assertTrue(True)             # 布尔断言
        self.assertGreater(5, 3)          # 大小断言
        self.assertIn("a", ["a", "b"])    # 包含断言

class TestExample(unittest.TestCase):

    # @classmethod
    # def setUpClass(cls):
    #     """类级别初始化，只执行一次"""
    #     cls.service = SomeService()
    #
    # def setUp(self):
    #     """每个测试方法运行前执行"""
    #     print("每次执行测试前:我先执行,我是每次执行测试的前置动作")
    # 我们的第一个测试用了 .每一个测试用例是以test_ 开头的
    def test_something(self):
        self.assertEqual(1 + 1, 2)  # 相等断言
        self.assertTrue(True)  # 布尔断言
        self.assertGreater(5, 3)  # 大小断言
        self.assertIn("a", ["a", "b"])  # 包含断言


        #SmartVoyage/demo/test_demo.py
        # 最后面 -v 就是打印测试结果
       #python -m  unittest SmartVoyage.demo.test_demo -v
    # 运行单个测试类,这里是测试TestExample 这个测试类
    #python -m unittest SmartVoyage.demo.test_demo.TestExample -v
    # 只测试某一个测试用例 test_something
    #python -m unittest SmartVoyage.demo.test_demo.TestExample.test_something -v
