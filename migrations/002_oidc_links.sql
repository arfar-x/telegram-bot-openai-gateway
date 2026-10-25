-- Link a Telegram account through an OpenID Connect device sign-in.
--
-- A link is either an API key (pairing, as before) or a refresh token for an issuer
-- (device sign-in). The bot never stores a password.
ALTER TABLE links ALTER COLUMN api_key_enc DROP NOT NULL;
ALTER TABLE links ADD COLUMN kind              text NOT NULL DEFAULT 'api_key'
    CHECK (kind IN ('api_key', 'oidc'));
ALTER TABLE links ADD COLUMN subject           text;
ALTER TABLE links ADD COLUMN refresh_token_enc text;
ALTER TABLE links ADD COLUMN status            text NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'expired'));
ALTER TABLE links ADD COLUMN refreshed_at      timestamptz;
ALTER TABLE links ADD CONSTRAINT links_kind_shape CHECK (
    (kind = 'api_key' AND api_key_enc IS NOT NULL AND subject IS NULL AND refresh_token_enc IS NULL)
    OR (kind = 'oidc' AND api_key_enc IS NULL AND subject IS NOT NULL)
);
CREATE INDEX links_subject ON links (subject) WHERE subject IS NOT NULL;

-- A sign-in in progress, so it survives a restart.
CREATE TABLE device_logins (
    telegram_user_id          bigint PRIMARY KEY,
    chat_id                   bigint NOT NULL,
    username                  text NOT NULL,
    telegram_name             text NOT NULL,
    device_code_enc           text NOT NULL,
    user_code                 text NOT NULL,
    verification_uri          text NOT NULL,
    verification_uri_complete text,
    interval_seconds          integer NOT NULL DEFAULT 5,
    expires_at                timestamptz NOT NULL,
    created_at                timestamptz NOT NULL DEFAULT now()
);
