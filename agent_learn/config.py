import os
# 放到环境变量里面更安全
API_KEY = os.getenv('DASHSCOPE_API_KEY')
class Config:
    def __init__(self):
        self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        # self.api_key = os.getenv('DASHSCOPE_API_KEY')
        self.api_key = API_KEY
        self.model_name = 'qwen-plus'