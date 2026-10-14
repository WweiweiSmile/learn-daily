"""配置。全部从环境变量 / server/.env 读。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 模型接入（OpenAI 兼容协议）----
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_temperature: float = 0.3

    # 空闲看门狗：两个数据块之间最长等多久（秒）。模型算得久不要紧，
    # 只要它还在往外吐字就不算超时。K3 这类推理模型一次要跑好几分钟，
    # 用固定总超时会把它误杀。
    llm_idle_timeout: float = 120.0

    # ---- 认证（认证中心 call-auth）----
    # 本服务**只验签、不签发**：登录/注册/续期都打认证中心，这里只需要公钥地址。
    # 好处是新增服务不用分发任何密钥，任何一个服务被攻破也伪造不了 token
    auth_jwks_url: str = "http://localhost:8020/.well-known/jwks.json"
    auth_issuer: str = "call-auth"
    auth_audience: str = "learn-daily"
    # 允许的时钟偏差（秒）。签发方和验签方的时钟不可能完全一致
    auth_leeway_seconds: int = 60
    # 拉取公钥的超时。认证中心不可达时，不该把这个请求挂死
    auth_jwks_timeout: int = 10

    # ---- 存储 ----
    data_dir: Path = BASE_DIR / "data"

    # ---- CORS ----
    # 允许的前端源，逗号分隔。默认 "*" = 不限来源；生产请在 .env 里填具体源。
    # 生产是跨域的：前端 http://learn.qwnet.top 打后端 http://learn-back.qwnet.top
    cors_origins: str = ""

    # 允许的请求方法，逗号分隔。"*" 表示不限，**含 OPTIONS** —— 跨域预检靠它放行
    cors_allow_methods: str = "*"

    # 允许的请求头，逗号分隔。Authorization 必须在里面，否则带 token 的跨域请求
    # 会在预检这一步就被浏览器拒掉
    cors_allow_headers: str = "Authorization,Content-Type"

    # ---- 按天切分 ----
    # 一天的目标字数。到了这个量就切一天。
    day_target_chars: int = 6000
    # 单天硬上限，超过就拆成两天。
    day_max_chars: int = 12000
    # 单天下限，最后一天不足这个量就并进前一天。
    day_min_chars: int = 1500

    @property
    def users_dir(self) -> Path:
        return self.data_dir / "users"

    def upload_dir_for(self, user_id: int) -> Path:
        """上传的原始文件也按用户分开放。

        目前没有下载原件的接口，所以放一起也不会直接泄露；但那是「碰巧安全」——
        哪天加了「下载原文」就会漏。一开始就分开，省得以后回头补
        """
        return self.users_dir / str(user_id) / "uploads"

    def database_url_for(self, user_id: int) -> str:
        """每个用户一个数据库文件。

        用物理隔离而不是「一张表加 user_id 列」：后者要求每个查询都记得加过滤，
        而漏一处就是越权读别人的数据 —— 漏的方式有无数种（`session.get(Day, id)`
        这种按主键取的地方最容易忘）。分文件之后越权在物理上不可能发生
        """
        return f"sqlite:///{self.users_dir / f'{user_id}.db'}"


settings = Settings()
