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

