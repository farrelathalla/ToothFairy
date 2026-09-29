-- Gateway schema. The gateway is the single writer, so the shape here is the source of
-- truth for identity and case state; the ML service holds no database at all.
--
-- `detections.json` is deliberately NOT mirrored into a column: the inference run writes it
-- to the shared results directory and the web app loads it statically from its own origin,
-- so copying it here would only create a second copy to keep in sync.

PRAGMA journal_mode = WAL;      -- readers never block the job worker's progress writes
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT    NOT NULL UNIQUE,
    name          TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'doctor',   -- 'admin' | 'doctor'
    password_hash TEXT    NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                TEXT    PRIMARY KEY,
    doctor_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    patient_name      TEXT,
    anamnesa          TEXT    NOT NULL DEFAULT '{}',   -- JSON blob
    status            TEXT    NOT NULL DEFAULT 'draft',
    progress          INTEGER NOT NULL DEFAULT 0,
    stage             TEXT,
    dataset_id        TEXT,
    error             TEXT,
    diagnosis_md      TEXT,
    recommendation_md TEXT,
    sanity_md         TEXT,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_doctor ON cases(doctor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS case_images (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id  TEXT    NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    view_key TEXT    NOT NULL,
    path     TEXT    NOT NULL,                          -- relative to UPLOAD_DIR
    UNIQUE(case_id, view_key)                           -- one photo per view slot
);

CREATE INDEX IF NOT EXISTS idx_case_images_case ON case_images(case_id);
