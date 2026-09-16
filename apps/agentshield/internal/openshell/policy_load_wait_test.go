package openshell

import (
	"os"
	"reflect"
	"testing"
	"time"
)

func TestApplyAndRollbackWaitForPolicyLoad(t *testing.T) {
	active := testdata(t, "policy_get_full.txt")
	writes := 0
	c := New(Options{Timeout: 8 * time.Second, PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
		if len(args) > 1 && args[1] == "get" {
			return 0, active, ""
		}
		if len(args) >= 5 && args[1] == "set" {
			if !reflect.DeepEqual(args[5:], []string{"--wait", "--timeout", "6"}) {
				t.Errorf("missing bounded load acknowledgement: %v", args[5:])
				return 1, "", "unsupported"
			}
			b, err := os.ReadFile(args[4])
			if err != nil {
				t.Error(err)
				return 1, "", "read failed"
			}
			writes++
			rev := "2"
			if writes == 2 {
				rev = "3"
			}
			active = policyOutput(rev, string(b))
			return 0, "Policy version " + rev + " submitted (hash: c0ffee)", "loaded"
		}
		return 1, "", "unexpected"
	}})
	base, err := c.ReadEffective("owned")
	if err != nil {
		t.Fatal(err)
	}
	rec, err := c.ApplyNetwork("owned", []NetworkRule{{Endpoint: "safe.test:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, base.Revision)
	if err != nil {
		t.Fatal(err)
	}
	if err := restoreEnforcementPolicy(c, "owned", rec, base); err != nil {
		t.Fatal(err)
	}
	if writes != 2 {
		t.Fatalf("writes=%d", writes)
	}
}

func TestUnconfirmedPolicyLoadNeverFallsBackOrReportsApplied(t *testing.T) {
	for _, rc := range []int{1, 124} {
		t.Run(map[int]string{1: "unsupported_or_failed", 124: "timeout_after_submission"}[rc], func(t *testing.T) {
			reads, writes := 0, 0
			c := New(Options{Timeout: 500 * time.Millisecond, PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
				if len(args) > 1 && args[1] == "get" {
					reads++
					return 0, testdata(t, "policy_get_full.txt"), ""
				}
				if len(args) >= 5 && args[1] == "set" {
					writes++
					if !reflect.DeepEqual(args[5:], []string{"--wait", "--timeout", "1"}) {
						t.Errorf("unbounded/omitted wait: %v", args)
					}
					return rc, "Policy version 2 submitted (hash: c0ffee)", "load not confirmed"
				}
				return 1, "", "unexpected"
			}})
			rec, err := c.ApplyNetwork("owned", []NetworkRule{{Endpoint: "safe.test:443", Effect: "allow", BinaryPaths: []string{"/usr/bin/curl"}}}, "1")
			if err == nil || rec.Result != "" || writes != 1 || reads != 2 {
				t.Fatalf("unconfirmed write accepted/retried: %v %#v writes=%d reads=%d", err, rec, writes, reads)
			}
		})
	}
}
