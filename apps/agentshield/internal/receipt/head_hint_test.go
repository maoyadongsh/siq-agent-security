package receipt

import (
	"os"
	"path/filepath"
	"testing"
)

func TestHeadHintFailureDoesNotSkipDurableReceiptOrCheckpoint(t *testing.T) {
	dir := t.TempDir()
	k := key(t)
	c, err := OpenChain(dir, "local", k)
	if err != nil {
		t.Fatal(err)
	}
	cp, err := OpenCheckpointStore(dir, k)
	if err != nil {
		t.Fatal(err)
	}
	c.AttachCheckpointStore(cp)
	// An unreplaceable hint models a locked/denied HEAD without changing ACLs.
	if err := os.Mkdir(filepath.Join(c.dir, "HEAD"), 0700); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ {
		r := Receipt{ReceiptID: "cache-fixture", Platform: "workbuddy", SessionID: "s", Tool: "Read", Action: "deny", EnforcementMode: "block"}
		if err := c.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	rows, err := c.Read()
	if err != nil || len(rows) != 2 || Verify(rows, k.Public()) != nil {
		t.Fatal("durable chain invalid", err)
	}
	tip, err := cp.Load("local")
	if err != nil || VerifyDetailed(rows, k.Public(), tip).HistoryIntegrity != HistoryVerified {
		t.Fatal("checkpoint not published", err)
	}
	reopened, err := OpenChain(dir, "local", k)
	if err != nil {
		t.Fatal(err)
	}
	seq, hash := reopened.Head()
	if seq != 1 || hash != rows[1].Hash {
		t.Fatal("recovery trusted the broken hint")
	}
	// An authoritative checkpoint failure must still propagate.
	if err := os.Remove(cp.Path("local")); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(cp.Path("local"), 0700); err != nil {
		t.Fatal(err)
	}
	if err := c.Append(&Receipt{Platform: "workbuddy", Action: "deny"}); err == nil {
		t.Fatal("checkpoint failure ignored")
	}
}
