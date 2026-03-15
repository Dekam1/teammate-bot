CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    id BIGINT PRIMARY KEY,
    username TEXT,
    name TEXT NOT NULL,
    age INT,
    gender TEXT NOT NULL,
    seeking TEXT NOT NULL,
    bio TEXT,
    avatar_file_id TEXT,
    is_premium BOOLEAN DEFAULT FALSE,
    premium_until TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    daily_likes INT DEFAULT 0,
    likes_reset_at TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE user_games (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    game TEXT NOT NULL,
    rank TEXT,
    roles TEXT[],
    play_style TEXT,
    UNIQUE(user_id, game)
);

CREATE TABLE likes (
    id SERIAL PRIMARY KEY,
    from_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    to_user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(from_user_id, to_user_id)
);

CREATE TABLE matches (
    id SERIAL PRIMARY KEY,
    user1_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    user2_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user1_id, user2_id)
);

CREATE TABLE blocked_users (
    blocker_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    blocked_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(blocker_id, blocked_id)
);

CREATE INDEX idx_user_games_user ON user_games(user_id);
CREATE INDEX idx_likes_to ON likes(to_user_id);
CREATE INDEX idx_matches_users ON matches(user1_id, user2_id);
