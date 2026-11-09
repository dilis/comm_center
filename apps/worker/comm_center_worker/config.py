"""The worker's settings, read from the environment (and ``.env`` at the repository root).

The worker knows nothing about the database or the API's internals: it needs the API's address and
its own account, and a few knobs for its loops.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # How the worker reaches the API and signs in (a worker account, see `create-worker`).
    worker_api_url: str = "http://127.0.0.1:8000"
    worker_name: str = ""
    worker_secret: str = ""
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR or CRITICAL
    worker_poll_interval_seconds: float = 2.0  # idle wait between cycles, and the session interval
    worker_max_attempts: int = 3  # sends per message before it is reported failed
    worker_backoff_base_seconds: float = 2.0  # wait before the 2nd attempt; doubles each time
    worker_heartbeat_file: str = "/tmp/comm-center-worker.heartbeat"  # touched when the API answers
    # The fake provider imitates a modem: each send takes this long (plus up to the jitter).
    worker_fake_send_delay_seconds: float = 2.0
    worker_fake_send_jitter_seconds: float = 1.0

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
