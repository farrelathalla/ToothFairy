// Package auth issues and verifies the gateway's credentials.
//
// Passwords are bcrypt-hashed (never stored or logged in the clear); sessions are stateless
// HS256 JWTs carrying only the user id, role and expiry — no patient data ever goes in a
// token, because a JWT is readable by anyone holding it.
package auth

import (
	"errors"
	"fmt"
	"strconv"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"golang.org/x/crypto/bcrypt"
)

// ErrInvalidToken covers every rejection reason. The caller must not tell a client *why* a
// token failed — that distinction is only useful to an attacker.
var ErrInvalidToken = errors.New("invalid or expired token")

// MinPasswordLen matches what the account form enforces client-side.
const MinPasswordLen = 6

func HashPassword(plain string) (string, error) {
	if len(plain) < MinPasswordLen {
		return "", fmt.Errorf("password must be at least %d characters", MinPasswordLen)
	}
	// bcrypt silently truncates past 72 bytes, so reject rather than accept a weakened hash.
	if len(plain) > 72 {
		return "", errors.New("password must be at most 72 characters")
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(plain), bcrypt.DefaultCost)
	return string(hash), err
}

// CheckPassword is a constant-time comparison by construction (bcrypt).
func CheckPassword(hash, plain string) bool {
	return bcrypt.CompareHashAndPassword([]byte(hash), []byte(plain)) == nil
}

type Claims struct {
	Role string `json:"role"`
	jwt.RegisteredClaims
}

type Issuer struct {
	secret []byte
	ttl    time.Duration
}

func NewIssuer(secret string, ttl time.Duration) *Issuer {
	return &Issuer{secret: []byte(secret), ttl: ttl}
}

func (i *Issuer) TTL() time.Duration { return i.ttl }

func (i *Issuer) Issue(userID int64, role string) (string, error) {
	nowT := time.Now()
	claims := Claims{
		Role: role,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   strconv.FormatInt(userID, 10),
			IssuedAt:  jwt.NewNumericDate(nowT),
			NotBefore: jwt.NewNumericDate(nowT),
			ExpiresAt: jwt.NewNumericDate(nowT.Add(i.ttl)),
			Issuer:    "toothfairy-gateway",
		},
	}
	return jwt.NewWithClaims(jwt.SigningMethodHS256, claims).SignedString(i.secret)
}

// Verify parses and validates a token, pinning the algorithm to HS256. Accepting whatever
// `alg` the token asks for is the classic JWT forgery hole, so the key function refuses
// anything else outright.
func (i *Issuer) Verify(tokenString string) (int64, string, error) {
	token, err := jwt.ParseWithClaims(tokenString, &Claims{}, func(t *jwt.Token) (any, error) {
		if _, ok := t.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method %v", t.Header["alg"])
		}
		return i.secret, nil
	}, jwt.WithValidMethods([]string{jwt.SigningMethodHS256.Alg()}),
		jwt.WithIssuer("toothfairy-gateway"))

	if err != nil || !token.Valid {
		return 0, "", ErrInvalidToken
	}
	claims, ok := token.Claims.(*Claims)
	if !ok {
		return 0, "", ErrInvalidToken
	}
	userID, err := strconv.ParseInt(claims.Subject, 10, 64)
	if err != nil {
		return 0, "", ErrInvalidToken
	}
	return userID, claims.Role, nil
}
