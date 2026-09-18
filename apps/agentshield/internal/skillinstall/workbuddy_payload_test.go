package skillinstall

import (
	"context"
	"os"
	"path/filepath"
	"siq-agent-security/apps/agentshield/internal/skillimport"
	"testing"
)

func TestWorkBuddyIndependentPayloadOwnership(t *testing.T) {
	for _, changed := range []string{"target", "pool"} {
		t.Run(changed, func(t *testing.T) {
			destination, pool := t.TempDir(), t.TempDir()
			raw := []byte("synthetic Skill payload\n")
			file := skillimport.File{Path: "SKILL.md", Bytes: int64(len(raw)), SHA256: hash(raw)}
			source, target := opaque(pool, "f", 0), filepath.Join(destination, file.Path)
			if err := writeOpaque(source, raw, false); err != nil {
				t.Fatal(err)
			}
			if err := publishOpaque(context.Background(), source, target, false, false); err != nil {
				t.Fatal(err)
			}
			a, _ := os.Stat(source)
			b, _ := os.Stat(target)
			if os.SameFile(a, b) {
				t.Fatal("payload shares operation pool inode")
			}
			if err := ownedFile(context.Background(), destination, pool, file, 0, "workbuddy"); err != nil {
				t.Fatal("independent matching payload rejected", err)
			}
			path := target
			if changed == "pool" {
				path = source
			}
			if err := os.WriteFile(path, []byte("changed"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := ownedFile(context.Background(), destination, pool, file, 0, "workbuddy"); err == nil {
				t.Fatal("changed ownership content accepted")
			}
		})
	}
}
