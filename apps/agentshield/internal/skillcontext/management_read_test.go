package skillcontext

import (
	"context"
	"os"
	"testing"
)

func TestManagementRecordsRecoverIssueAndRevocation(t *testing.T) {
	f := newFixture(t)
	c := f.issue(t, "")
	rows, err := f.store.ManagementRecords(context.Background(), testInstall)
	if err != nil || len(rows) != 1 || rows[0].Context.Signature != c.Signature || rows[0].Revoked {
		t.Fatalf("issue readback: %v %+v", err, rows)
	}
	other, err := f.store.ManagementRecords(context.Background(), "another-install")
	if err != nil || len(other) != 0 {
		t.Fatal("cross-install disclosure", err)
	}
	if _, err := f.store.RevokeExpected(c.ContextID, c.Signature); err != nil {
		t.Fatal(err)
	}
	rows, err = f.store.ManagementRecords(context.Background(), testInstall)
	if err != nil || len(rows) != 1 || !rows[0].Revoked || rows[0].Context.Signature != c.Signature {
		t.Fatal("revocation readback", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := f.store.ManagementRecords(ctx, testInstall); err == nil {
		t.Fatal("cancelled read succeeded")
	}
	if err := os.WriteFile(f.store.revokedPath(c.ContextID), []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := f.store.ManagementRecords(context.Background(), testInstall); err == nil {
		t.Fatal("corrupt revocation treated as active")
	}
}
