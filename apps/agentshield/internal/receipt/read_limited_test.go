package receipt

import (
	"strings"
	"testing"
)

func TestReadLimitedStopsAtMaxRecordsWithoutFullLoadSemantics(t *testing.T) {
	key := key(t)
	chain, err := OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 5; i++ {
		r := Receipt{
			Platform: "hermes", SessionID: "s", Tool: "read_file", Action: "allow",
			Reason: "ok", EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	res, err := chain.ReadLimited(ReadLimit{MaxRecords: 2, MaxBytes: 1 << 20})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Receipts) != 2 {
		t.Fatalf("want 2 receipts, got %d", len(res.Receipts))
	}
	if !res.Truncated {
		t.Fatal("must mark truncated when more records remain on disk")
	}
	if res.DiskBudget {
		t.Fatal("record cap must not be reported as disk byte budget")
	}
	all, err := chain.Read()
	if err != nil || len(all) != 5 {
		t.Fatalf("full Read still required for verify path: %d %v", len(all), err)
	}
}

func TestReadLimitedStopsAtMaxBytes(t *testing.T) {
	key := key(t)
	chain, err := OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	// Large reason forces multi-KB lines so a tiny MaxBytes stops early.
	big := strings.Repeat("x", 2000)
	for i := 0; i < 10; i++ {
		r := Receipt{
			Platform: "hermes", SessionID: "s", Tool: "read_file", Action: "allow",
			Reason: big, EnforcementMode: "block",
		}
		if err := chain.Append(&r); err != nil {
			t.Fatal(err)
		}
	}
	res, err := chain.ReadLimited(ReadLimit{MaxRecords: 100, MaxBytes: 3500})
	if err != nil {
		t.Fatal(err)
	}
	if !res.Truncated || !res.DiskBudget {
		t.Fatalf("want disk budget truncate, got %+v len=%d", res, len(res.Receipts))
	}
	if len(res.Receipts) >= 10 {
		t.Fatalf("disk budget must stop before loading all receipts, got %d", len(res.Receipts))
	}
	if res.BytesScanned > 3500 {
		t.Fatalf("scanned %d exceeds budget", res.BytesScanned)
	}
}

func TestReadLimitedCompleteUnderBudget(t *testing.T) {
	key := key(t)
	chain, err := OpenChain(t.TempDir(), "local", key)
	if err != nil {
		t.Fatal(err)
	}
	r := Receipt{Platform: "hermes", SessionID: "s", Tool: "t", Action: "allow", Reason: "ok", EnforcementMode: "block"}
	if err := chain.Append(&r); err != nil {
		t.Fatal(err)
	}
	res, err := chain.ReadLimited(ReadLimit{MaxRecords: 10, MaxBytes: 1 << 20})
	if err != nil {
		t.Fatal(err)
	}
	if res.Truncated || res.DiskBudget || len(res.Receipts) != 1 {
		t.Fatalf("complete under budget: %+v", res)
	}
}
