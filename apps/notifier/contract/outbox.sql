-- The contract between the API and the notifier: the two tables they share (SPECS.md, Phase 9).
--
-- The API writes: it adds `push_subscription` rows (a person turned notifications on) and queues
-- `push_outbox` rows when a message arrives, in the same transaction as the message. The notifier
-- reads and updates `push_outbox`, reads `push_subscription`, and deletes both kinds of row.
-- Anything that does the same against these tables can replace the notifier.
--
-- Rules both sides follow:
--  * A subscription has at most one `pending` row (`pending_key` is unique): a new message for a
--    subscription that has one joins it (message_count + 1, last_message_id, the sender added to
--    `senders`, `send_after` unchanged). A row being sent is `sending` and is never joined.
--  * `send_after` and `lease_until` are naive UTC.
--  * Whoever sends deletes the row on success, and deletes the subscription when the push service
--    says it is gone (404 or 410); the rows of a deleted subscription go with it.
--
-- The API's own migrations create these tables (alembic 0016 and 0017); the API's
-- tests/test_notifier_contract.py fails if its tables and this file drift apart. `user_id` is a
-- foreign key to the API's `users` table there; here it is only a column, since users are not part
-- of the contract.

CREATE TABLE push_subscription (
  id bigint NOT NULL AUTO_INCREMENT,
  user_id bigint NOT NULL,
  endpoint text NOT NULL,
  endpoint_hash varchar(64) NOT NULL,
  p256dh varchar(255) NOT NULL,
  auth varchar(255) NOT NULL,
  user_agent varchar(255) DEFAULT NULL,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_push_subscription_endpoint_hash (endpoint_hash),
  KEY ix_push_subscription_user_id (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE push_outbox (
  id bigint NOT NULL AUTO_INCREMENT,
  subscription_id bigint NOT NULL,
  state varchar(8) NOT NULL DEFAULT 'pending',
  pending_key bigint GENERATED ALWAYS AS (IF(state = 'pending', subscription_id, NULL)) VIRTUAL,
  message_count int NOT NULL DEFAULT 1,
  last_message_id bigint DEFAULT NULL,
  senders json NOT NULL,
  send_after datetime NOT NULL,
  attempts int NOT NULL DEFAULT 0,
  lease_until datetime DEFAULT NULL,
  last_error varchar(255) DEFAULT NULL,
  created_at datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_push_outbox_pending_key (pending_key),
  KEY ix_push_outbox_state_send_after (state, send_after),
  KEY ix_push_outbox_subscription_id (subscription_id),
  CONSTRAINT fk_push_outbox_subscription_id FOREIGN KEY (subscription_id)
    REFERENCES push_subscription (id) ON DELETE CASCADE,
  CONSTRAINT ck_push_outbox_state CHECK (state IN ('pending', 'sending'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
