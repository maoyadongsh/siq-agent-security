package main

import (
	"crypto/ed25519"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

func main() {
	root := os.Args[1]
	read := func(n string) []byte {
		b, e := os.ReadFile(filepath.Join(root, n))
		if e != nil {
			panic(e)
		}
		return b
	}
	pub, e := base64.StdEncoding.DecodeString(string(read("public-key.base64")))
	if e != nil || len(pub) != 32 {
		panic("public key")
	}
	sig, e := hex.DecodeString(string(read("signature.hex")))
	if e != nil || len(sig) != 64 {
		panic("signature")
	}
	msg := read("message.canon")
	good := ed25519.Verify(pub, msg, sig)
	changed := append([]byte(nil), msg...)
	changed[len(changed)/2] ^= 1
	badSig := append([]byte(nil), sig...)
	badSig[0] ^= 1
	r := map[string]bool{"actual_export_verified": good, "changed_message_rejected": !ed25519.Verify(pub, changed, sig), "changed_signature_rejected": !ed25519.Verify(pub, msg, badSig), "foreign_public_key_rejected": !ed25519.Verify(make([]byte, 32), msg, sig)}
	raw, _ := json.MarshalIndent(r, "", "  ")
	fmt.Println(string(raw))
	for _, v := range r {
		if !v {
			os.Exit(1)
		}
	}
}
