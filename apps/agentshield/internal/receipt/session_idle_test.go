package receipt

import (
	"errors"
	"sync/atomic"
	"testing"
	"time"
)

func TestUntaintedIdleExpiresAllowsFreshSameID(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	var clock atomic.Value
	clock.Store(time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC))
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		MaxSessions: 4, SessionIdleTTL: 5 * time.Second,
		Now:    func() time.Time { return clock.Load().(time.Time) },
		Grants: fx.eng.opts.Grants,
	})
	if err != nil {
		t.Fatal(err)
	}
	req := Request{Platform: "hermes", SessionID: "clean", AgentID: "inst_1", Tool: "read_file",
		Params: map[string]any{"path": "~/work/out/a.txt"}}
	if _, err := eng.Decide(req); err != nil {
		t.Fatal(err)
	}
	if eng.SessionStats().Active != 1 {
		t.Fatalf("active=%d", eng.SessionStats().Active)
	}
	clock.Store(clock.Load().(time.Time).Add(6 * time.Second))
	if _, err := eng.Decide(req); err != nil {
		t.Fatal(err)
	}
	st := eng.SessionStats()
	if st.IdleExpired < 1 {
		t.Fatalf("expected idle expiry, stats=%+v", st)
	}
	if st.Active != 1 {
		t.Fatalf("fresh session should replace expired, active=%d", st.Active)
	}
	if s := eng.sessions["clean"]; s == nil || len(s.taints) != 0 {
		t.Fatalf("fresh session must be clean: %+v", s)
	}
}

func TestTaintedNeverIdleExpires(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	var clock atomic.Value
	clock.Store(time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC))
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		MaxSessions: 1, SessionIdleTTL: 5 * time.Second,
		Now:    func() time.Time { return clock.Load().(time.Time) },
		Grants: fx.eng.opts.Grants,
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
	clock.Store(clock.Load().(time.Time).Add(time.Hour))
	_, err = eng.Decide(Request{
		Platform: "hermes", SessionID: "fresh", AgentID: "inst_1", Tool: "read_file",
		Params: map[string]any{"path": "~/work/out/b.txt"},
	})
	if !errors.Is(err, ErrSessionCapacity) {
		t.Fatalf("tainted must still occupy slot after idle, got %v", err)
	}
	if eng.SessionStats().IdleExpired != 0 {
		t.Fatalf("tainted must not idle-expire: %+v", eng.SessionStats())
	}
	if s := eng.sessions["tainted"]; s == nil || !s.taints[taintSecret] {
		t.Fatal("taint must remain")
	}
}

func TestIdleSweepFreesCapacityForNewSession(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	var clock atomic.Value
	clock.Store(time.Date(2026, 9, 6, 12, 0, 0, 0, time.UTC))
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		MaxSessions: 1, SessionIdleTTL: 5 * time.Second,
		Now:    func() time.Time { return clock.Load().(time.Time) },
		Grants: fx.eng.opts.Grants,
	})
	if err != nil {
		t.Fatal(err)
	}
	req := func(sid string) Request {
		return Request{Platform: "hermes", SessionID: sid, AgentID: "inst_1", Tool: "read_file",
			Params: map[string]any{"path": "~/work/out/a.txt"}}
	}
	if _, err := eng.Decide(req("old")); err != nil {
		t.Fatal(err)
	}
	if _, err := eng.Decide(req("new")); !errors.Is(err, ErrSessionCapacity) {
		t.Fatalf("before expiry want capacity, got %v", err)
	}
	clock.Store(clock.Load().(time.Time).Add(6 * time.Second))
	if _, err := eng.Decide(req("new")); err != nil {
		t.Fatalf("after untainted idle sweep new must succeed: %v", err)
	}
	if eng.sessions["old"] != nil {
		t.Fatal("expired untainted old must be gone")
	}
	if eng.SessionStats().IdleExpired < 1 {
		t.Fatalf("stats %+v", eng.SessionStats())
	}
}

func TestSessionIdleTTLDisabledAndRange(t *testing.T) {
	g := deployedGrant(t, "hermes", false)
	fx := newFixture(t, "block", g, false)
	eng, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, EnforcementMode: "block", Version: "test",
		SessionIdleTTL: -1, Now: fx.eng.opts.Now, Grants: fx.eng.opts.Grants,
	})
	if err != nil {
		t.Fatal(err)
	}
	if eng.SessionStats().IdleTTLSeconds != 0 {
		t.Fatalf("disabled TTL must report 0 seconds, got %d", eng.SessionStats().IdleTTLSeconds)
	}
	if _, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, SessionIdleTTL: time.Millisecond, Grants: fx.eng.opts.Grants,
	}); err == nil {
		t.Fatal("sub-second TTL must fail")
	}
	if _, err := New(Options{
		Pack: fx.eng.opts.Pack, Chain: fx.chain, SessionIdleTTL: 48 * time.Hour, Grants: fx.eng.opts.Grants,
	}); err == nil {
		t.Fatal("oversize TTL must fail")
	}
}
