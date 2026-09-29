package auth

import (
	"strings"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func TestPasswordHashingRoundTrips(t *testing.T) {
	hash, err := HashPassword("secret123")
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(hash, "secret123") {
		t.Fatal("the plaintext password appears in its own hash")
	}
	if !CheckPassword(hash, "secret123") {
		t.Error("correct password rejected")
	}
	if CheckPassword(hash, "secret124") {
		t.Error("wrong password accepted")
	}
}

func TestHashingIsSaltedSoIdenticalPasswordsDiffer(t *testing.T) {
	a, _ := HashPassword("secret123")
	b, _ := HashPassword("secret123")
	if a == b {
		t.Error("two hashes of the same password are identical — no salt")
	}
}

func TestPasswordLengthBoundsAreEnforced(t *testing.T) {
	if _, err := HashPassword("short"); err == nil {
		t.Error("a 5-character password was accepted")
	}
	// bcrypt silently ignores bytes past 72; accepting one would weaken the hash invisibly.
	if _, err := HashPassword(strings.Repeat("a", 80)); err == nil {
		t.Error("an over-long password was accepted instead of rejected")
	}
}

func TestIssuedTokenVerifies(t *testing.T) {
	issuer := NewIssuer("a-secret-that-is-long-enough-here", time.Hour)
	token, err := issuer.Issue(42, "doctor")
	if err != nil {
		t.Fatal(err)
	}
	id, role, err := issuer.Verify(token)
	if err != nil {
		t.Fatalf("verify: %v", err)
	}
	if id != 42 || role != "doctor" {
		t.Errorf("got (%d, %q), want (42, \"doctor\")", id, role)
	}
}

func TestTokenSignedWithAnotherSecretIsRejected(t *testing.T) {
	mine := NewIssuer("a-secret-that-is-long-enough-here", time.Hour)
	theirs := NewIssuer("a-different-secret-of-good-length", time.Hour)

	token, _ := theirs.Issue(1, "admin")
	if _, _, err := mine.Verify(token); err == nil {
		t.Error("a token signed with another key verified")
	}
}

func TestExpiredTokenIsRejected(t *testing.T) {
	issuer := NewIssuer("a-secret-that-is-long-enough-here", -time.Minute)
	token, _ := issuer.Issue(1, "doctor")
	if _, _, err := issuer.Verify(token); err == nil {
		t.Error("an expired token verified")
	}
}

func TestAlgNoneForgeryIsRejected(t *testing.T) {
	// The classic JWT hole: a token asking to be verified with "none". The key function
	// pins HS256, so this must never authenticate.
	claims := Claims{Role: "admin", RegisteredClaims: jwt.RegisteredClaims{
		Subject:   "1",
		Issuer:    "toothfairy-gateway",
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
	}}
	forged, err := jwt.NewWithClaims(jwt.SigningMethodNone, claims).
		SignedString(jwt.UnsafeAllowNoneSignatureType)
	if err != nil {
		t.Fatal(err)
	}
	issuer := NewIssuer("a-secret-that-is-long-enough-here", time.Hour)
	if _, _, err := issuer.Verify(forged); err == nil {
		t.Error("an alg=none token was accepted")
	}
}

func TestGarbageTokenIsRejectedWithoutPanicking(t *testing.T) {
	issuer := NewIssuer("a-secret-that-is-long-enough-here", time.Hour)
	for _, token := range []string{"", "abc", "a.b.c", strings.Repeat("x", 5000)} {
		if _, _, err := issuer.Verify(token); err == nil {
			t.Errorf("token %.10q accepted", token)
		}
	}
}
