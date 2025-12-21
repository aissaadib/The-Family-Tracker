CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    role TEXT,
    lat REAL,
    lon REAL,
    last_update INTEGER
);

INSERT OR IGNORE INTO people (name, role, lat, lon, last_update) VALUES
('Amine',  'Father', 34.020882, -6.841650, strftime('%s','now')),
('Meryeme','Mother', 34.020500, -6.842200, strftime('%s','now')),
('Adam',   'Son 1',  34.021000, -6.840900, strftime('%s','now')),
('Youssef','Son 2',  34.021200, -6.842000, strftime('%s','now'));
