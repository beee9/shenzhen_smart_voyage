import os

# 项目根目录
project_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

# 生产环境
# env = "prod"
# 测试环境
env = "prod"


# 开发环境
# env = "dev"
# 预生产环境
# env = "pre_prod"

# 定义配置文件
class Config:

    def __init__(self):
        # 大模型配置
        self.base_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        self.api_key = os.getenv("DASHSCOPE_API_KEY") # 大模型的key一般也是配到环境变量中,不会写死到代码中的
        self.model_name = 'qwen3.6-plus'
        self.temperature = 0.1

        # 数据库配置
        self.host = 'localhost'
        self.user = 'smart_yoyage'
        self.password = '123456'  # 不是root #真实环境,密码不会使用明文存储.一般是加密的,通过密钥来进行解密使用.
        self.database = 'travel_rag'
        # Milvus 向量数据库配置（docker/docker-compose.yml 启动）
        # 注意：Milvus 2.x 默认不开认证（authorizationEnabled=false），
        # 所以不需要用户名密码，直接 connect(host, port) 即可。
        # compose 里的 minioadmin / 1234 分别是 MinIO 和 Redis 的，走容器内网，与本客户端无关。
        self.milvus_host = 'localhost'
        self.milvus_port = 19530
        self.tour_group_collection = 'tour_groups'
        # Embedding 配置（阿里云 DashScope，旅游团语义检索用）
        self.embedding_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings'
        self.embedding_model = 'text-embedding-v3'
        self.embedding_dim = 1024
        # 日志配置
        self.log_file = os.path.join(project_root, 'SmartVoyage', 'logs/app.log')

        # 票务查询的12306接口地址
        self.url_123 = ""
        # 天气数据源配置
        # 可选值："database"（从数据库获取） / "api"（直接从和风API获取）
        self.weather_source = "api"
        self.qweather_api_key = os.getenv("QWEATHER_API_KEY", "")
        self.qweather_host = "m7487r6ych.re.qweatherapi.com"

        #意图识别的配置,
        self.intent = {
            "weather": "WeatherQueryAssistant",

            "flight": "TicketAssistant",
            "train": "TicketAssistant",
            "concert": "TicketAssistant",
            "order": "TicketAssistant",

            "car_rental": "TripAssistant",
            "tour_group": "TripAssistant",
            "insurance": "TripAssistant",
            "trip_order": "TripAssistant",
        }



    def get_mysql_config(self, env):
        """
        通过不同的环境获取不同的数据库配置
        :return:
        """
        if env == 'prod':
            self.host = 'localhost'
            self.user = 'root'
            self.password = 'root'
            self.database = 'travel_rag'
        elif env == 'dev':
            self.host = 'localhost1'
            self.user = 'root1'
            self.password = 'root1'
            self.database = 'travel_rag'
        elif env == 'test':
            self.host = 'localhost2'
            self.user = 'root2'
            self.password = 'root2'
            self.database = 'travel_rag'
        else:
            self.host = 'localhost3'
            self.user = 'root3'
            self.password = 'root3'
            self.database = 'travel_rag'

        return self.host, self.user, self.password, self.database


if __name__ == '__main__':
    print(Config().log_file)
    print(Config().get_mysql_config(env))