package store

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"time"
)

type Role string

const (
	RoleAdmin  Role = "admin"
	RoleDoctor Role = "doctor"
)

func (r Role) Valid() bool { return r == RoleAdmin || r == RoleDoctor }

type User struct {
	ID           int64     `json:"id"`
	Email        string    `json:"email"`
	Name         string    `json:"name"`
	Role         Role      `json:"role"`
	IsActive     bool      `json:"is_active"`
	CreatedAt    time.Time `json:"created_at"`
	PasswordHash string    `json:"-"` // never serialized
}

const userColumns = `id, email, name, role, password_hash, is_active, created_at`

func scanUser(row interface{ Scan(...any) error }) (*User, error) {
	var u User
	var created string
	var active int
	if err := row.Scan(&u.ID, &u.Email, &u.Name, &u.Role, &u.PasswordHash, &active, &created); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	u.IsActive = active == 1
	u.CreatedAt = parseTime(created)
	return &u, nil
}

// NormalizeEmail lower-cases and trims, so "  Admin@X.io " and "admin@x.io" are one account.
func NormalizeEmail(email string) string { return strings.ToLower(strings.TrimSpace(email)) }

func (s *Store) CreateUser(ctx context.Context, email, name string, role Role, passwordHash string) (*User, error) {
	email = NormalizeEmail(email)
	res, err := s.db.ExecContext(ctx,
		`INSERT INTO users (email, name, role, password_hash, is_active, created_at)
		 VALUES (?, ?, ?, ?, 1, ?)`,
		email, name, string(role), passwordHash, now())
	if err != nil {
		if strings.Contains(strings.ToLower(err.Error()), "unique") {
			return nil, ErrEmailTaken
		}
		return nil, err
	}
	id, err := res.LastInsertId()
	if err != nil {
		return nil, err
	}
	return s.GetUser(ctx, id)
}

func (s *Store) GetUser(ctx context.Context, id int64) (*User, error) {
	return scanUser(s.db.QueryRowContext(ctx,
		`SELECT `+userColumns+` FROM users WHERE id = ?`, id))
}

func (s *Store) GetUserByEmail(ctx context.Context, email string) (*User, error) {
	return scanUser(s.db.QueryRowContext(ctx,
		`SELECT `+userColumns+` FROM users WHERE email = ?`, NormalizeEmail(email)))
}

func (s *Store) ListUsers(ctx context.Context) ([]*User, error) {
	rows, err := s.db.QueryContext(ctx,
		`SELECT `+userColumns+` FROM users ORDER BY id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	users := []*User{}
	for rows.Next() {
		u, err := scanUser(rows)
		if err != nil {
			return nil, err
		}
		users = append(users, u)
	}
	return users, rows.Err()
}

// UserUpdate carries only the fields a PATCH actually supplied.
type UserUpdate struct {
	Name         *string
	Role         *Role
	IsActive     *bool
	PasswordHash *string
}

func (s *Store) UpdateUser(ctx context.Context, id int64, up UserUpdate) (*User, error) {
	sets := []string{}
	args := []any{}
	if up.Name != nil {
		sets = append(sets, "name = ?")
		args = append(args, *up.Name)
	}
	if up.Role != nil {
		sets = append(sets, "role = ?")
		args = append(args, string(*up.Role))
	}
	if up.IsActive != nil {
		active := 0
		if *up.IsActive {
			active = 1
		}
		sets = append(sets, "is_active = ?")
		args = append(args, active)
	}
	if up.PasswordHash != nil {
		sets = append(sets, "password_hash = ?")
		args = append(args, *up.PasswordHash)
	}
	if len(sets) == 0 {
		return s.GetUser(ctx, id)
	}

	args = append(args, id)
	res, err := s.db.ExecContext(ctx,
		`UPDATE users SET `+strings.Join(sets, ", ")+` WHERE id = ?`, args...)
	if err != nil {
		return nil, err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return nil, ErrNotFound
	}
	return s.GetUser(ctx, id)
}

func (s *Store) DeleteUser(ctx context.Context, id int64) error {
	res, err := s.db.ExecContext(ctx, `DELETE FROM users WHERE id = ?`, id)
	if err != nil {
		return err
	}
	if n, _ := res.RowsAffected(); n == 0 {
		return ErrNotFound
	}
	return nil
}

// CountAdmins backs the "never delete or demote the last admin" rule.
func (s *Store) CountAdmins(ctx context.Context) (int, error) {
	var n int
	err := s.db.QueryRowContext(ctx,
		`SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1`).Scan(&n)
	return n, err
}
