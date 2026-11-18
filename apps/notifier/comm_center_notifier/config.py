"""The notifier's settings, read from the environment (and ``.env`` at the repository root).

It knows the database (the outbox tables, see contract/outbox.sql) and the push services, and
nothing else: no API address, no API code.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # The same database as the API. A user that may only read and change the two push tables is
    # enough (SELECT, UPDATE and DELETE on push_outbox; SELECT and DELETE on push_subscription).
    database_url: str = "mysql+pymysql://comm_center:comm_center@127.0.0.1:3307/comm_center"
    # Identify this server to the push services. The pair comes from the API's
    # `python -m app.cli vapid-keys`; the public half also goes to the API (it is the browser's key).
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = ""  # a mailto: or https: contact for the push services
    # A failed send is retried after the base delay, doubling each time, and given up after the
    # maximum number of attempts.
    push_max_attempts: int = 6
    push_retry_base_seconds: int = 30
    notifier_poll_seconds: float = 1  # idle wait between looks at the outbox
    notifier_lease_seconds: int = 60  # a send that takes longer is assumed to have died
    notifier_heartbeat_file: str = "/tmp/comm-center-notifier.heartbeat"  # touched every cycle
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR or CRITICAL

    model_config = SettingsConfigDict(env_file="../../.env", extra="ignore")


settings = Settings()
