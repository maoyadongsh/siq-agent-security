package receipt

import (
	"encoding/json"
	"errors"
	"os"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/grant"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func confirmationRequest(d *Decision) ConfirmationResolve {
	return ConfirmationResolve{SchemaVersion: "local-confirmation-resolve/v1", DecisionReceiptID: d.Receipt.ReceiptID, DecisionHash: d.Receipt.Hash, ParamsDigest: d.Receipt.ParamsDigest, Approve: true, ActorID: "reviewer"}
}
func TestConfirmationsSingleResolutionAndRecovery(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
	d, err := fx.eng.Decide(r)
	if err != nil || d.Action != ActionHold {
		t.Fatal(d, err)
	}
	before, _ := fx.chain.Read()
	list := fx.eng.Confirmations()
	if len(list.Items) != 1 || list.Items[0].Status != "pending" || list.Items[0].DecisionHash != d.Receipt.Hash {
		t.Fatal(list)
	}
	for i := 0; i < 4; i++ {
		fx.eng.Confirmations()
	}
	after, _ := fx.chain.Read()
	if !reflect.DeepEqual(before, after) {
		t.Fatal("read changed chain")
	}
	request := confirmationRequest(d)
	for _, mutate := range []func(*ConfirmationResolve){
		func(r *ConfirmationResolve) { r.DecisionHash = strings.Repeat("0", 64) }, func(r *ConfirmationResolve) { r.ParamsDigest = strings.Repeat("0", 64) }, func(r *ConfirmationResolve) { r.DecisionReceiptID = "other" },
	} {
		bad := request
		mutate(&bad)
		if _, err = fx.eng.ResolveConfirmation(d.Receipt.ActionID, bad); !errors.Is(err, ErrConfirmationConflict) {
			t.Fatal(err)
		}
	}
	var wg sync.WaitGroup
	var successes atomic.Int32
	for i := 0; i < 12; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, err := fx.eng.ResolveConfirmation(d.Receipt.ActionID, request)
			if err == nil {
				successes.Add(1)
			} else if !errors.Is(err, ErrConfirmationConflict) {
				t.Error(err)
			}
		}()
	}
	wg.Wait()
	if successes.Load() != 1 {
		t.Fatal("duplicate approvals", successes.Load())
	}
	all, _ := fx.chain.Read()
	if len(all) != 2 || all[1].RecordType != "hold_resolution" || all[1].DecisionReceiptID != d.Receipt.ReceiptID || Verify(all, fx.k.Public()) != nil {
		t.Fatal("missing unique signed audit")
	}
	fx.eng, err = New(fx.eng.opts)
	if err != nil {
		t.Fatal(err)
	}
	if fx.eng.Confirmations().Items[0].Status != "approved" {
		t.Fatal("lost resolution")
	}
	if _, err = fx.eng.ResolveConfirmation(d.Receipt.ActionID, request); !errors.Is(err, ErrConfirmationConflict) {
		t.Fatal("restart replay", err)
	}
	changed := statusRequest(r, d)
	changed.Params = map[string]any{"command": "changed"}
	if _, err = fx.eng.ReadHoldStatus(changed); err == nil {
		t.Fatal("changed parameters approved")
	}
	if _, err = fx.eng.Observe(correlatedRequest(r, d), "fixture"); err != nil {
		t.Fatal(err)
	}
	if fx.eng.Confirmations().Items[0].Status != "consumed" {
		t.Fatal("missing consumption")
	}
}
func TestConfirmationsDenyDeadlineAuthorityAndAuditFailure(t *testing.T) {
	for _, kind := range []string{"deny", "deadline", "revoked", "grant_expired", "audit_failure", "actor"} {
		t.Run(kind, func(t *testing.T) {
			g := deployedGrant(t, "openclaw", false)
			fx := newFixture(t, "block", g, false)
			r := req("openclaw", "exec", map[string]any{"command": "printf fixture"})
			d, err := fx.eng.Decide(r)
			if err != nil {
				t.Fatal(err)
			}
			body := confirmationRequest(d)
			want := "pending"
			switch kind {
			case "deny":
				body.Approve = false
				want = "denied"
			case "deadline":
				deadline, _ := time.Parse(time.RFC3339Nano, *fx.eng.Confirmations().Items[0].ExpiresAt)
				fx.eng.opts.Now = func() time.Time { return deadline }
				want = "expired"
			case "revoked":
				g.Status = "revoked"
				want = "unavailable"
			case "grant_expired":
				value := fx.clock.Format(time.RFC3339Nano)
				g.ExpiresAt = &value
				want = "unavailable"
			case "actor":
				body.ActorID = "  \n  "
			case "audit_failure":
				files, e := fx.chain.files()
				if e != nil {
					t.Fatal(e)
				}
				if e = os.Remove(files[0]); e != nil {
					t.Fatal(e)
				}
				if e = os.Mkdir(files[0], 0700); e != nil {
					t.Fatal(e)
				}
			}
			_, err = fx.eng.ResolveConfirmation(d.Receipt.ActionID, body)
			if kind == "deny" {
				if err != nil {
					t.Fatal(err)
				}
			} else if err == nil {
				t.Fatal("unsafe approval", kind)
			}
			if fx.eng.Confirmations().Items[0].Status != want {
				t.Fatal(kind, fx.eng.Confirmations())
			}
			if kind == "deny" {
				if _, err = fx.eng.Observe(correlatedRequest(r, d), "forged"); err == nil {
					t.Fatal("denied call observed")
				}
			}
			if kind == "deadline" {
				if _, err = fx.eng.ResolveHold(d.Receipt, true, "reviewer"); !errors.Is(err, ErrHoldExpired) {
					t.Fatal("legacy deadline", err)
				}
			}
		})
	}
}
func TestConfirmationContractSamples(t *testing.T) {
	fx := newFixture(t, "block", deployedGrant(t, "openclaw", false), false)
	d, err := fx.eng.Decide(req("openclaw", "exec", map[string]any{"command": "printf fixture"}))
	if err != nil {
		t.Fatal(err)
	}
	list := fx.eng.Confirmations()
	c := &list.Items[0]
	c.ActionID = "act-fixture"
	c.DecisionReceiptID = "rcpt-fixture"
	c.DecisionHash = strings.Repeat("1", 64)
	c.GrantID = "grt-fixture"
	c.IssuedAt = "2026-09-10T01:00:00Z"
	expiry := "2026-09-10T01:05:00Z"
	c.ExpiresAt = &expiry
	body := confirmationRequest(d)
	body.DecisionReceiptID = c.DecisionReceiptID
	body.DecisionHash = c.DecisionHash
	for name, value := range map[string]any{"local-confirmations.v1": list, "local-confirmation-resolve.v1": body} {
		raw, _ := json.MarshalIndent(value, "", "  ")
		raw = append(raw, '\n')
		path := "../../testdata/contracts/" + name + ".sample.json"
		if os.Getenv("AGENTSHIELD_UPDATE_SAMPLES") == "1" {
			if err = os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
		}
		expected, e := os.ReadFile(path)
		if e != nil || string(expected) != string(raw) {
			t.Fatal(name, "contract differs", e)
		}
	}
}

func TestConfirmationsBindingWithdrawalAndOrder(t *testing.T) {
	fx, store, binding := revocableEngine(t, "required", "block")
	g := deployedGrant(t, "hermes", false)
	g.OpenClawToolPolicy = &grant.OpenClawToolPolicy{RequireApproval: []string{"read_file"}}
	fx.eng.opts.Grants = func(_, _ string) *grant.Grant { return g }
	r := req("hermes", "read_file", map[string]any{"path": "/work/report"})
	first, err := fx.eng.Decide(r)
	if err != nil || first.Action != ActionHold {
		t.Fatal(first, err)
	}
	r.ToolCallID = "second-call"
	second, err := fx.eng.Decide(r)
	if err != nil || second.Action != ActionHold {
		t.Fatal(second, err)
	}
	list := fx.eng.Confirmations()
	if len(list.Items) != 2 || list.Items[0].ActionID != second.Receipt.ActionID || list.Items[1].ActionID != first.Receipt.ActionID {
		t.Fatal("unstable order", list)
	}
	if list.Items[0].ParamsExcerpt != nil {
		*list.Items[0].ParamsExcerpt = "changed projection"
		if *fx.eng.Confirmations().Items[0].ParamsExcerpt == "changed projection" {
			t.Fatal("caller mutated receipt")
		}
	}
	if _, err = store.RevokeIntent(binding.IntentID, binding.IntentDigest); err != nil {
		t.Fatal(err)
	}
	for _, item := range fx.eng.Confirmations().Items {
		if item.Status != "unavailable" {
			t.Fatal("revoked binding remains actionable", item)
		}
	}
	if _, err = fx.eng.ResolveConfirmation(first.Receipt.ActionID, confirmationRequest(first)); !errors.Is(err, ErrConfirmationConflict) {
		t.Fatal(err)
	}
}
