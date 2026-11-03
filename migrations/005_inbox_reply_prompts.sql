-- A delivered message the bot sent only to ask for a reply (a prompt) is removed once the reply was passed on.
ALTER TABLE inbox_replies ADD COLUMN prompt boolean NOT NULL DEFAULT false;
