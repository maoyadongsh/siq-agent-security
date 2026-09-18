package receipt

import (
	"testing"
	"time"
)

func TestStageTimingFollowsExecutedBranchesAndPreservesDecisions(t *testing.T) {
	for _, required := range []bool{false, true} {
		t.Run(map[bool]string{false: "optional", true: "required"}[required], func(t *testing.T) {
			fx := newFixture(t, "block", nil, false)
			fx.eng.opts.Now = func() time.Time { return time.Date(2026, 9, 8, 1, 0, 0, 0, time.UTC) }
			if required {
				fx.eng.opts.IntentEnforcement = "required"
			}
			fx.eng.opts.IntentLookup = func(string, string, string) (*IntentContract, error) { return nil, nil }
			req := Request{Platform: "hermes", SessionID: "timing", AgentID: "a1", Tool: "read_file", Params: map[string]any{"path": "/work/report"}}
			before, err := fx.eng.Decide(req)
			if err != nil {
				t.Fatal(err)
			}
			// Only the observed lookup deliberately waits. Fast executed stages may
			// legitimately measure zero; the frozen authority clock must still not
			// become the performance clock for this measurable lookup.
			const minimumLookupElapsed = 2 * time.Millisecond
			fx.eng.opts.IntentLookup = func(string, string, string) (*IntentContract, error) {
				started := time.Now()
				for attempt := 0; attempt < 16; attempt++ {
					time.Sleep(time.Millisecond)
					if time.Since(started) >= minimumLookupElapsed {
						return nil, nil
					}
				}
				t.Fatal("monotonic lookup clock did not advance within bounded polling")
				return nil, nil
			}
			timings := map[string][]time.Duration{}
			fx.eng.opts.StageTiming = func(stage string, d time.Duration) { timings[stage] = append(timings[stage], d) }
			after, err := fx.eng.Decide(req)
			if err != nil {
				t.Fatal(err)
			}
			if before.Action != after.Action || before.Receipt.ReasonCode != after.Receipt.ReasonCode {
				t.Fatal("timing changed security decision")
			}
			for _, stage := range []string{"authority_validation", "intent_lookup", "runtime_action_normalization", "receipt_append_fsync"} {
				if len(timings[stage]) != 1 || timings[stage][0] < 0 {
					t.Fatal("missing or negative monotonic sample", stage, timings)
				}
			}
			if timings["intent_lookup"][0] < minimumLookupElapsed {
				t.Fatal("lookup timing must advance despite frozen authority clock", timings["intent_lookup"])
			}
			if len(timings["context_validation"]) != 0 {
				t.Fatal("unexecuted context stage reported")
			}
			for _, stage := range []string{"provenance_resolution", "policy_evaluation"} {
				want := 1
				if required {
					want = 0
				}
				if len(timings[stage]) != want {
					t.Fatal("incorrect stage denominator", stage, timings)
				}
			}
		})
	}
}
