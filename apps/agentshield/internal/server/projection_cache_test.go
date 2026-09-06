package server

import (
	"testing"
)

func TestProjectionCacheStableAcrossGets(t *testing.T) {
	s, _ := newServer(t, "block")
	code, b1 := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("first get: %d %v", code, b1)
	}
	p1, _ := b1["projection"].(map[string]any)
	rev1 := p1["revision"]
	if rev1 == nil || rev1 == float64(0) {
		t.Fatalf("missing revision: %v", p1)
	}
	code, b2 := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("second get: %d %v", code, b2)
	}
	p2, _ := b2["projection"].(map[string]any)
	if p2["revision"] != rev1 {
		t.Fatalf("GET must not rebuild projection each time: %v -> %v", rev1, p2["revision"])
	}
	if p2["health"] != "ok" {
		t.Fatalf("health: %v", p2)
	}
	s.invalidateProjection("test")
	code, bStale := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("rebuild after invalidate: %d %v", code, bStale)
	}
	pStale, _ := bStale["projection"].(map[string]any)
	if pStale["revision"] == rev1 {
		t.Fatal("stale invalidate must cause one rebuild with new revision")
	}
	if pStale["health"] != "ok" {
		t.Fatalf("successful rebuild must be ok: %v", pStale)
	}
	rev2 := pStale["revision"]
	code, b3 := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("third get: %d %v", code, b3)
	}
	if b3["projection"].(map[string]any)["revision"] != rev2 {
		t.Fatal("ok projection must stay cached across GET")
	}
	if err := s.Refresh(""); err != nil {
		t.Fatal(err)
	}
	code, b4 := call(t, s, "GET", "/v1/assets", token, nil)
	if code != 200 {
		t.Fatalf("after refresh: %d %v", code, b4)
	}
	if b4["projection"].(map[string]any)["revision"] == rev2 {
		t.Fatal("controlled Refresh must advance revision")
	}
}
