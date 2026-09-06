package receipt

import (
	"errors"
	"testing"
)

func TestSessionCapacityRefusesNewIDKeepsExisting(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		MaxSessions: 2,
		Now:         fx.eng.opts.Now,
		Grants:      fx.eng.opts.Grants,
	})
	if err != nil {
		t.Fatal(err)
	}

	req := func(sid string) Request {
		return Request{Platform: "hermes", SessionID: sid, AgentID: "inst_1", Tool: "read_file",
			Params: map[string]any{"path": "~/work/out/a.txt"}}
	}
	if _, err := eng.Decide(req("s1")); err != nil {
		t.Fatalf("s1: %v", err)
	}
	if _, err := eng.Decide(req("s2")); err != nil {
		t.Fatalf("s2: %v", err)
	}
	_, err = eng.Decide(req("s3"))
	if !errors.Is(err, ErrSessionCapacity) {
		t.Fatalf("s3 must be capacity refuse, got %v", err)
	}
	st := eng.SessionStats()
	if st.Active != 2 || st.Max != 2 || st.Refusals != 1 {
		t.Fatalf("stats %+v", st)
	}
	if _, err := eng.Decide(req("s1")); err != nil {
		t.Fatalf("existing s1 must still decide: %v", err)
	}
	if eng.SessionStats().Active != 2 {
		t.Fatal("must not grow or shrink sessions on existing ID")
	}
}

func TestSessionCapacityNeverEvictsTainted(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		MaxSessions: 1,
		Now:         fx.eng.opts.Now,
		Grants:      fx.eng.opts.Grants,
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = eng.Decide(Request{
		Platform: "hermes", SessionID: "tainted", AgentID: "inst_1", Tool: "read_file",
		Params: map[string]any{"path": "~/work/out/a.txt", "token": "sk-abcdefghijklmnopqrstuvwxyz012345"},
	})
	if err != nil {
		t.Fatal(err)
	}
	s := eng.sessions["tainted"]
	if s == nil || !s.taints[taintSecret] {
		t.Fatalf("expected secret taint, got %+v", s)
	}
	_, err = eng.Decide(Request{
		Platform: "hermes", SessionID: "fresh", AgentID: "inst_1", Tool: "read_file",
		Params: map[string]any{"path": "~/work/out/b.txt"},
	})
	if !errors.Is(err, ErrSessionCapacity) {
		t.Fatalf("must refuse rather than LRU-evict tainted session: %v", err)
	}
	if eng.sessions["tainted"] == nil || !eng.sessions["tainted"].taints[taintSecret] {
		t.Fatal("tainted session must remain; eviction would fake a clean session")
	}
	if _, ok := eng.sessions["fresh"]; ok {
		t.Fatal("refused session must not be allocated")
	}
}

func TestMaxSessionsRange(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	eng, err := New(Options{Pack: fx.eng.opts.Pack, Chain: fx.chain, MaxSessions: 0})
	if err != nil {
		t.Fatalf("0 must default: %v", err)
	}
	if eng.SessionStats().Max != defaultMaxSessions {
		t.Fatalf("default max %d", eng.SessionStats().Max)
	}
	if _, err := New(Options{Pack: fx.eng.opts.Pack, Chain: fx.chain, MaxSessions: -1}); err == nil {
		t.Fatal("negative MaxSessions must fail")
	}
	if _, err := New(Options{Pack: fx.eng.opts.Pack, Chain: fx.chain, MaxSessions: maxMaxSessions + 1}); err == nil {
		t.Fatal("oversize MaxSessions must fail")
	}
}
