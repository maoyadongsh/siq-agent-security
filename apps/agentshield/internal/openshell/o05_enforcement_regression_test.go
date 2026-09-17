package openshell

import (
	"errors"
	"os"
	"testing"
)

func TestEnforcementDenialCannotComeFromUnknownOrTransportErrors(t *testing.T) {
	cases := []struct {
		out  string
		err  error
		want string
	}{
		{`{"status":403}`, nil, fetchBlocked}, {`{"status":200}`, nil, fetchArrived},
		{`{"status":403}`, errors.New("timeout"), fetchUnknown},
		{`{"error":"transport_failure"}`, nil, fetchUnknown}, {`{"status":500}`, nil, fetchUnknown},
		{`{"status":404}`, nil, fetchUnknown}, {``, nil, fetchUnknown}, {`FETCHERR HTTPError`, nil, fetchUnknown},
		{`{"status":403} {"status":200}`, nil, fetchUnknown},
	}
	for _, tc := range cases {
		got := classifyEnforcementFetch(tc.out, tc.err)
		if got != tc.want {
			t.Fatalf("classification=%s want=%s", got, tc.want)
		}
		if (requireEnforcementDenied(got, 0) == nil) != (tc.want == fetchBlocked) {
			t.Fatal("invalid denial assertion")
		}
	}
	if requireEnforcementDenied(fetchBlocked, 1) == nil {
		t.Fatal("403 with arrival is not an enforced deny")
	}
}

func TestEnforcementRestoreUsesReceiptAndRejectsDrift(t *testing.T) {
	for _, drift := range []bool{false, true} {
		t.Run(map[bool]string{false: "restores", true: "drift_refused"}[drift], func(t *testing.T) {
			active := testdata(t, "policy_get_full.txt")
			writes := 0
			c := New(Options{PollInterval: -1, policyCoordinator: newPolicyCoordinator(), Runner: func(args []string) (int, string, string) {
				if len(args) > 1 && args[1] == "get" {
					return 0, active, ""
				}
				if len(args) == 8 && args[1] == "set" {
					b, err := os.ReadFile(args[4])
					if err != nil {
						t.Fatal(err)
					}
					writes++
					rev := "2"
					if writes > 1 {
						rev = "3"
					}
					active = policyOutput(rev, string(b))
					return 0, "Policy version " + rev + " submitted (hash: c0ffee)", ""
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
			if drift {
				active = policyOutput("99", policyBody(t, active))
			}
			err = restoreEnforcementPolicy(c, "owned", rec, base)
			if drift {
				if err == nil || writes != 1 {
					t.Fatal("drift overwritten")
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			snap, err := c.ReadEffective("owned")
			if err != nil || snap.PolicyDigest != base.PolicyDigest || writes != 2 {
				t.Fatal("exact restore not verified")
			}
		})
	}
}

func TestEnforcementProbeParsesOnlyBoundedSuccessfulStdout(t *testing.T) {
	for _, tc := range []struct {
		rc                    int
		out, diagnostic, want string
	}{
		{0, `{"status":403}`, "connection diagnostic", fetchBlocked},
		{1, `{"status":403}`, "execution failed", fetchUnknown},
		{0, `{"status":403}`, string(make([]byte, 300)), fetchUnknown},
		{0, `{"error":"transport_failure"}`, "", fetchUnknown},
	} {
		c := New(Options{MaxOutput: 256, Runner: func([]string) (int, string, string) { return tc.rc, tc.out, tc.diagnostic }})
		if got := execSandboxFetch(t, c, "owned", "/usr/bin/python3", "http://example.test"); got != tc.want {
			t.Fatalf("got %s want %s", got, tc.want)
		}
	}
}
