from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-secret-change-me-dev-only-secret"
DEV_WEBHOOK_SECRET = "dev-only-webhook-secret-change-me-dev-only"


class Settings(BaseSettings):
    # Defaults match docker-compose.yml so tests and dev work out of the box.
    database_url: str = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/comm_center"
    # Signs access and refresh tokens. The default is for development only: set a long random
    # value (for example `openssl rand -hex 32`) anywhere else.
    jwt_secret: str = DEV_JWT_SECRET
    # Derives each Android device's webhook signing key (see `webhook-info`). Set a long random value
    # anywhere else; changing it means re-entering the key in every phone.
    webhook_secret: str = DEV_WEBHOOK_SECRET
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60
    # Workers sign in again when this runs out (they have no refresh token).
    worker_token_ttl_seconds: int = 15 * 60
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR or CRITICAL (API and worker)
    # Login rate limiting: this many failures for one username (or LOGIN_MAX_FAILURES_PER_IP
    # for one client address) within the lockout window block further attempts until the oldest
    # of them ages out.
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 20
    login_lockout_seconds: int = 15 * 60
    # Same window, for other endpoints: wrong current passwords in PUT /auth/me/password (per
    # user) and invalid refresh tokens in POST /auth/refresh (per client address).
    password_max_failures: int = 5
    refresh_max_failures_per_ip: int = 30
    # Region used to read phone numbers typed without a country code.
    default_phone_region: str = "PH"

    # GSM worker (a separate process, see docs/DEPLOYMENT.md).
    # How the worker reaches the API and signs in (a worker account, see `create-worker`).
    worker_api_url: str = "http://127.0.0.1:8000"
    worker_name: str = ""
    worker_secret: str = ""
    worker_poll_interval_seconds: float = 2.0  # idle wait between cycles
    worker_max_attempts: int = 3  # sends per message before it is marked failed
    worker_backoff_base_seconds: float = 2.0  # wait before the 2nd attempt; doubles each time
    # A worker that claims a message holds it for this long (it can extend); past that the message
    # is failed, never re-sent. Claim requests may wait up to the long-poll time for a message.
    worker_lease_seconds: int = 120
    worker_long_poll_seconds: int = 20
    # The fake provider imitates a modem: each send takes this long (plus up to the jitter).
    worker_fake_send_delay_seconds: float = 2.0
    worker_fake_send_jitter_seconds: float = 1.0
    worker_heartbeat_file: str = "/tmp/comm-center-worker.heartbeat"  # touched every cycle

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
