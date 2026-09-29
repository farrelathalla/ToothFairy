// Package store owns all persistence for the gateway: accounts, cases and uploaded images.
//
// SQLite via the pure-Go `modernc.org/sqlite` driver, so the gateway cross-compiles and runs
// with no cgo toolchain. The schema is applied at open time (see schema.sql) — it is small
// enough that idempotent `CREATE TABLE IF NOT EXISTS` is honest migration, and it keeps a
// fresh clone one command from a working database.
//
// **One writer.** SQLite allows a single writer at a time, and the job workers write progress
// frequently, so the write pool is capped at one connection and WAL is enabled: readers
// (status polling, history) then never block behind a running job.
package store

import (
	"context"
	"database/sql"
	_ "embed"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"time"

	_ "modernc.org/sqlite"
)

//go:embed schema.sql
var schema string

// ErrNotFound is returned by every lookup that addresses a single row.
var ErrNotFound = errors.New("not found")

// ErrEmailTaken is returned when an account would violate the unique email constraint.
var ErrEmailTaken = errors.New("email already registered")

type Store struct {
	db *sql.DB
}

func Open(path string) (*Store, error) {
	if dir := filepath.Dir(path); dir != "" && dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, fmt.Errorf("create database dir: %w", err)
		}
	}
	// _txlock=immediate takes the write lock at BEGIN, which turns the "database is locked"
	// race between two concurrent writers into an ordinary wait.
	dsn := fmt.Sprintf("file:%s?_pragma=busy_timeout(5000)&_pragma=foreign_keys(1)&_txlock=immediate", path)
	db, err := sql.Open("sqlite", dsn)
	if err != nil {
		return nil, fmt.Errorf("open database: %w", err)
	}
	db.SetMaxOpenConns(1)
	db.SetConnMaxLifetime(0)

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("ping database: %w", err)
	}
	if _, err := db.Exec(schema); err != nil {
		return nil, fmt.Errorf("apply schema: %w", err)
	}
	return &Store{db: db}, nil
}

func (s *Store) Close() error { return s.db.Close() }

// DB exposes the handle for tests that need to assert on raw rows.
func (s *Store) DB() *sql.DB { return s.db }

func now() string { return time.Now().UTC().Format(time.RFC3339Nano) }

func parseTime(s string) time.Time {
	t, err := time.Parse(time.RFC3339Nano, s)
	if err != nil {
		return time.Time{}
	}
	return t
}

// tx runs fn inside a transaction, rolling back on any error or panic.
func (s *Store) tx(ctx context.Context, fn func(*sql.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer func() {
		if p := recover(); p != nil {
			_ = tx.Rollback()
			panic(p)
		}
	}()
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}
