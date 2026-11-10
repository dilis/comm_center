"""The worker's settings, read from the environment (and ``.env`` at the repository root).

The worker knows nothing about the database or the API's internals: it needs the API's address and
its own account, and a few knobs for its loops.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # How the worker reaches the API and signs in: as the agent of the device it serves (see
    # `register-device`), e.g. WORKER_NAME=gsm-fake.
    worker_api_url: str = "http://127.0.0.1:8000"
    worker_name: str = ""
    worker_secret: str = ""
    # What kind of device this worker runs and how to reach it; the API does not know or care.
    worker_provider: str = "fake"  # fake or android
    worker_android_base_url: str = ""  # the phone's address, e.g. http://192.168.1.50:8080
    worker_android_username: str = ""  # the phone's login (SMS Gateway for Android)
    worker_android_password: str = ""
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR or CRITICAL
    worker_poll_interval_seconds: float = 2.0  # idle wait between cycles, and the session interval
    worker_max_attempts: int = 3  # sends per message before it is reported failed
    worker_backoff_base_seconds: float = 2.0  # wait before the 2nd attempt; doubles each time
    worker_heartbeat_file: str = "/tmp/comm-center-worker.heartbeat"  # touched when the API answers
    worker_android_timeout_seconds: float = 15.0  # how long to wait for an Android phone to answer
    # The fake provider imitates a modem: each send takes this long (plus up to the jitter).
    worker_fake_send_delay_seconds: float = 2.0
    worker_fake_send_jitter_seconds: float = 1.0

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
