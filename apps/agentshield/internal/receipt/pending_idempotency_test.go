package receipt

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/pending"
)

func TestPendingCursorFailureReopenDoesNotDuplicateIndependentEvents(t *testing.T) {
	for _, local := range []bool{false, true} {
		t.Run(map[bool]string{false: "v1", true: "v2"}[local], func(t *testing.T) {
			fx := newFixture(t, "block", nil, false)
			dir := t.TempDir()
			p := pending.Record{Schema: pending.SchemaID, Platform: "hermes", RecordedAt: "2026-10-07T01:00:00Z", EnforcementMode: "block", Outcome: "deny", Reason: "unavailable"}
			if local {
				p.Schema = pending.LocalSchemaID
				p.Platform = "workbuddy"
				p.Outcome = "unconfirmed"
				p.Origin = "local_hook"
				p.Stage = "observation"
				p.ReasonCode = "workbuddy_observation_unconfirmed"
			}
			for i := 0; i < 2; i++ {
				if err := pending.Append(dir, p); err != nil {
					t.Fatal(err)
				}
			}
			cursor := filepath.Join(dir, "pending", "promoted.lines")
			// readCursor sees a missing cursor; create a directory only after signed append.
			_, err := pending.Promote(dir, func(event pending.Record) error {
				_, err := fx.eng.AppendPendingObserved(event)
				if err != nil {
					return err
				}
				return os.Mkdir(cursor, 0700)
			})
			if err == nil {
				t.Fatal("cursor failure not injected")
			}
			if seq, _ := fx.chain.Head(); seq != 0 {
				t.Fatalf("append not durable: %d", seq)
			}
			if err := os.Remove(cursor); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(dir, "pending", ".promoted.orphan"), []byte("999\n"), 0600); err != nil {
				t.Fatal(err)
			}
			// Reopen the signed chain and construct a new Engine (no in-memory dedup state).
			reopened, err := OpenChain(filepath.Dir(filepath.Dir(fx.chain.dir)), fx.chain.chainID, fx.k)
			if err != nil {
				t.Fatal(err)
			}
			opts := fx.eng.opts
			opts.Chain = reopened
			fresh, err := New(opts)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := pending.Promote(dir, func(event pending.Record) error { _, err := fresh.AppendPendingObserved(event); return err }); err != nil {
				t.Fatal(err)
			}
			records, err := reopened.Read()
			if err != nil {
				t.Fatal(err)
			}
			if len(records) != 2 || records[0].ReceiptID == records[1].ReceiptID {
				t.Fatalf("independent events lost or duplicated: %d", len(records))
			}
			if err := Verify(records, fx.k.Public()); err != nil {
				t.Fatal(err)
			}
			if local && (records[0].Action != "unknown" || records[0].RecordType != "local_failure" || records[0].LocalOrigin.Signed) {
				t.Fatal("local failure became authorization")
			}
			if fresh.SessionStats().Active != 0 {
				t.Fatal("pending history manufactured online sessions")
			}
			if os.Getenv("SIQ_UPDATE_CONTRACT_FIXTURES") == "1" {
				name := map[bool]string{false: "receipt-pending-source-v1.json", true: "receipt-pending-source-v2.json"}[local]
				raw, err := json.MarshalIndent(records[0], "", "  ")
				if err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(filepath.Join("..", "..", "testdata", "contracts", name), append(raw, '\n'), 0600); err != nil {
					t.Fatal(err)
				}
			}
			// Cursor loss after a clean promotion also recovers without adding either event.
			if err := os.Remove(cursor); err != nil {
				t.Fatal(err)
			}
			var wg sync.WaitGroup
			errs := make(chan error, 2)
			for i := 0; i < 2; i++ {
				wg.Add(1)
				go func() {
					defer wg.Done()
					_, err := pending.Promote(dir, func(event pending.Record) error { _, err := fresh.AppendPendingObserved(event); return err })
					errs <- err
				}()
			}
			wg.Wait()
			close(errs)
			for err := range errs {
				if err != nil {
					t.Fatal(err)
				}
			}
			if seq, _ := reopened.Head(); seq != 1 {
				t.Fatalf("concurrent replay grew chain: %d", seq)
			}
		})
	}
}

func TestPendingLegacyAmbiguityPreservesValidHistoricalChain(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	p := pending.Record{Platform: "hermes", RecordedAt: "2026-10-07T01:00:00Z", EnforcementMode: "block", Outcome: "deny", Reason: "unavailable"}
	if _, err := fx.eng.AppendPendingObserved(p); err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err := pending.Append(dir, p); err != nil {
		t.Fatal(err)
	}
	_, err := pending.Promote(dir, func(event pending.Record) error { _, err := fx.eng.AppendPendingObserved(event); return err })
	if err == nil || err.Error() != "receipt: historical pending source ambiguous" {
		t.Fatalf("legacy uncertainty hidden: %v", err)
	}
	records, err := fx.chain.Read()
	if err != nil {
		t.Fatal(err)
	}
	if len(records) != 1 || Verify(records, fx.k.Public()) != nil {
		t.Fatal("history invalidated or rewritten")
	}
}

func TestPendingBeforeAppendFailureRetries(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	dir := t.TempDir()
	if err := pending.Append(dir, pending.Record{Platform: "hermes", Outcome: "deny"}); err != nil {
		t.Fatal(err)
	}
	if _, err := pending.Promote(dir, func(pending.Record) error { return errors.New("injected before append") }); err == nil {
		t.Fatal("missing failure")
	}
	if seq, _ := fx.chain.Head(); seq != -1 {
		t.Fatal("failure created receipt")
	}
	if _, err := pending.Promote(dir, func(event pending.Record) error { _, err := fx.eng.AppendPendingObserved(event); return err }); err != nil {
		t.Fatal(err)
	}
	if seq, _ := fx.chain.Head(); seq != 0 {
		t.Fatal("event lost")
	}
}

func TestPendingFullSourceIdentityRejectsConflictingPayload(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	p := pending.Record{SourceID: strings.Repeat("a", 64), Platform: "hermes", Outcome: "deny", Reason: "unavailable"}
	first, err := fx.eng.AppendPendingObserved(p)
	if err != nil {
		t.Fatal(err)
	}
	again, err := fx.eng.AppendPendingObserved(p)
	if err != nil || again.Hash != first.Hash {
		t.Fatal("same source changed", err)
	}
	p.Reason = "different event claimed same source"
	if _, err := fx.eng.AppendPendingObserved(p); err == nil {
		t.Fatal("conflicting source silently accepted")
	}
	if seq, _ := fx.chain.Head(); seq != 0 {
		t.Fatal("conflict appended")
	}
	p.SourceID = "short"
	if _, err := fx.eng.AppendPendingObserved(p); err == nil {
		t.Fatal("short identity accepted")
	}
}
