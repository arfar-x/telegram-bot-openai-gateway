-- Which delivered inbox messages accept a reply, and the opaque reference to send it under.
CREATE TABLE inbox_replies (
  chat_id    bigint NOT NULL,
  message_id bigint NOT NULL,
  ref        text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (chat_id, message_id)
);
