package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestSkillAncestrySignedVersionAndValidation(t *testing.T) {
	signer, _ := NewSigner()
	pub, _ := signer.PublicKeyPEM()
	for _, scenario := range []string{"valid", "v1", "absent", "empty", "duplicate", "wrong-first", "bad-digest", "too-many"} {
		t.Run(scenario, func(t *testing.T) {
			collection := skillUploadFixture()
			collection.SchemaVersion = "enterprise-skill-collection/v2"
			item := &collection.Observations[0]
			item.AncestorSHA256 = []string{item.LocatorSHA256, strings.Repeat("c", 64)}
			switch scenario {
			case "v1":
				collection.SchemaVersion = "enterprise-skill-collection/v1"
			case "absent":
				item.AncestorSHA256 = nil
			case "empty":
				item.AncestorSHA256 = []string{}
			case "duplicate":
				item.AncestorSHA256[1] = item.LocatorSHA256
			case "wrong-first":
				item.AncestorSHA256[0] = strings.Repeat("d", 64)
			case "bad-digest":
				item.AncestorSHA256[1] = "/private/path"
			case "too-many":
				item.AncestorSHA256 = make([]string, 34)
			}
			body, _, err := prepareSkillUpload("tsk_fixture", json.RawMessage(`{"roots":["/fixture/skills"],"include":["SKILL.md"]}`), collection, signer)
			if scenario != "valid" {
				if err == nil {
					t.Fatal("invalid ancestry accepted")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			var wire map[string]any
			if json.Unmarshal(body, &wire) != nil || wire["schema_version"] != "enterprise-skill-upload/v2" {
				t.Fatal("version lost")
			}
			sig := wire["signature"].(string)
			delete(wire, "signature")
			signed, _ := CanonicalJSON(wire)
			if VerifySignature(pub, signed, sig) != nil {
				t.Fatal("invalid signature")
			}
			wire["observations"].([]any)[0].(map[string]any)["ancestor_sha256"] = []string{item.LocatorSHA256}
			changed, _ := CanonicalJSON(wire)
			if VerifySignature(pub, changed, sig) == nil {
				t.Fatal("ancestry not signed")
			}
		})
	}
}
