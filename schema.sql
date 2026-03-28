CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL,
    vis BOOLEAN DEFAULT 0,
    location TEXT
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    role TEXT,
    lat REAL,
    lon REAL,
    last_update INTEGER
);

CREATE TABLE IF NOT EXISTS p_map (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    location TEXT,
    FOREIGN KEY(user_id) REFERENCES users(id)
);


CREATE TABLE IF NOT EXISTS friend_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id INTEGER NOT NULL,
    to_user_id INTEGER NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at INTEGER NOT NULL,
    FOREIGN KEY(from_user_id) REFERENCES users(id),
    FOREIGN KEY(to_user_id) REFERENCES users(id),
    UNIQUE(from_user_id, to_user_id)
);

CREATE TABLE IF NOT EXISTS map_follows (
    user_id INTEGER NOT NULL,
    followed_id INTEGER NOT NULL,
    PRIMARY KEY (user_id, followed_id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    FOREIGN KEY(followed_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS map_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    note TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    scope TEXT DEFAULT 'public',
    FOREIGN KEY(user_id) REFERENCES users(id)
);
