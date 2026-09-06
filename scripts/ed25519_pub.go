// Command ed25519_pub reads a 32-byte Ed25519 seed (raw or standard base64)
// from stdin and prints only the public key and its SHA-256 fingerprint.
// It never writes the seed.
package main

import (
	"crypto/ed25519"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"strings"
)

func main() {
	raw, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintf(os.Stderr, "ed25519_pub: read stdin: %v\n", err)
		os.Exit(1)
	}
	text := strings.TrimSpace(string(raw))
	seed, err := base64.StdEncoding.DecodeString(text)
	if err != nil || len(seed) != ed25519.SeedSize {
		seed = []byte(text)
	}
	if len(seed) != ed25519.SeedSize {
		fmt.Fprintf(os.Stderr, "ed25519_pub: seed must be 32 bytes (raw or standard base64)\n")
		os.Exit(2)
	}
	pub := ed25519.NewKeyFromSeed(seed).Public().(ed25519.PublicKey)
	sum := sha256.Sum256(pub)
	fmt.Printf("public_key_b64=%s\n", base64.StdEncoding.EncodeToString(pub))
	fmt.Printf("sha256=%s\n", hex.EncodeToString(sum[:]))
}
