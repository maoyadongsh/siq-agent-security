package receipt

import (
 "encoding/json"
 "os"
 "testing"
 "time"
)

// Diagnostic only: does not replace the immutable official O04 measurements.
func TestReviewStageAttribution(t *testing.T) {
 if os.Getenv("SIQ_REVIEW_STAGE") != "1" { t.Skip("explicit diagnostic") }
 all := map[string]map[string][]float64{}
 for _, name := range []string{"A_allow", "B_allow", "B_revoked"} {
  var eng *Engine
  expected := ActionAllow
  if name == "A_allow" {
   fx := newFixture(t, "block", deployedGrant(t, "hermes", false), false)
   eng = fx.eng
  } else {
   fx, store, binding := revocableEngine(t, "required", "block")
   eng = fx.eng
   if name == "B_revoked" {
    if _, err := store.RevokeBinding(binding.BindingID, binding.IntentDigest); err != nil { t.Fatal(err) }
    expected = ActionDeny
   }
  }
  request := req("hermes", "read_file", map[string]any{"path": "/home/u/proj/a.txt"})
  for i:=0;i<5;i++ { d,err:=eng.Decide(request); if err!=nil || d.Action!=expected { t.Fatal("warmup outcome",err) } }
  samples:=map[string][]float64{}
  eng.opts.StageTiming=func(stage string, d time.Duration) {samples[stage]=append(samples[stage],float64(d)/float64(time.Millisecond))}
  for i:=0;i<200;i++ {
   begin:=time.Now(); d,err:=eng.Decide(request); elapsed:=time.Since(begin)
   if err!=nil || d.Action!=expected {t.Fatal("diagnostic outcome",err)}
   if name=="B_revoked" && d.Receipt.ReasonCode!="intent_binding_revoked" {t.Fatal("revocation reason")}
   samples["total"]=append(samples["total"],float64(elapsed)/float64(time.Millisecond))
  }
  all[name]=samples
 }
 raw,err:=json.Marshal(all);if err!=nil {t.Fatal(err)}
 t.Log("SIQ_REVIEW_STAGE="+string(raw))
}
