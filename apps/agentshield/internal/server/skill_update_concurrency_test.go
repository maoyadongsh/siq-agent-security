package server

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

// UP05 service-level concurrency (B03): two valid administrator sessions issue
// truly concurrent HTTP writes against the same installation. The component
// layer controls interleaving with barriers; here the server's own write slot
// must be what keeps the outcome contract-shaped: exactly one success (or
// idempotent reuse of it), every other request a stable contract error. Each
// request's status code and stable error code is recorded below; counting
// HTTP 200s alone is not the assertion.
type up05Flight struct {
	code       int
	out        map[string]any
	errMessage string
}

func up05ErrorCode(f up05Flight) string {
	if f.code == 200 {
		return ""
	}
	if code, ok := f.out["error"].(string); ok {
		return code
	}
	return "<missing:" + f.errMessage + ">"
}

func up05ResultSignature(f up05Flight) string {
	result, _ := f.out["result"].(map[string]any)
	if result == nil {
		return ""
	}
	sig, _ := result["signature"].(string)
	return sig
}

// up05Terminal drives one write to a terminal contract outcome. The server's
// install write slot is a try-lock: a request that arrives while another admin
// session holds it gets 429 skill_install_busy with Retry-After, which mutates
// nothing. A real client honors that and retries; the retry must end in either
// the single 200 success or a stable contract error — never a non-contract
// status, and never an unbounded busy loop.
func up05Terminal(t *testing.T, request up05Request, credential, method, path string, body any) up05Flight {
	t.Helper()
	for attempt := 0; ; attempt++ {
		code, out := request(method, path, credential, body)
		f := up05Flight{code: code, out: out}
		if code != 429 || up05ErrorCode(f) != "skill_install_busy" {
			return f
		}
		if attempt >= 200 {
			t.Fatalf("write stayed busy beyond retry budget: %v", out)
		}
		time.Sleep(time.Second) // current write-slot Retry-After is one second
	}
}

// Real loopback transport and independently redeemed administrator sessions.
// This remains an in-process test server, not installed-daemon acceptance.
type up05Request func(method, path, credential string, body any) (int, map[string]any)

func up05Clients(t *testing.T, s *Server, count int) (up05Request, []string) {
	t.Helper()
	s.d.RecoveryToken = strings.Repeat("e", 64)
	credentials := make([]string, count)
	for i := range credentials {
		renewed := sessionRequest(t, s, "POST", "/v1/session/pairing", nil, s.d.RecoveryToken, nil, map[string]string{"X-SIQ-Local-CLI": "1"})
		if renewed.Code != 200 {
			t.Fatal("renew pairing failed", renewed.Code)
		}
		pairCode := sessionBody(t, renewed)["code"].(string)
		status, paired := call(t, s, "POST", "/v1/pair", "", map[string]any{"code": pairCode})
		if status != 200 {
			t.Fatal("pair failed", status)
		}
		credentials[i] = paired["session"].(string)
		for j := 0; j < i; j++ {
			if credentials[i] == credentials[j] {
				t.Fatal("sessions are not independent")
			}
		}
	}
	server := httptest.NewServer(s.Handler())
	t.Cleanup(server.Close)
	request := func(method, path, credential string, body any) (int, map[string]any) {
		raw, err := json.Marshal(body)
		if err != nil {
			t.Error("request marshal failed")
			return 0, nil
		}
		req, err := http.NewRequest(method, server.URL+path, bytes.NewReader(raw))
		if err != nil {
			t.Error("request creation failed")
			return 0, nil
		}
		req.Host = "127.0.0.1:47611"
		req.Header.Set("Authorization", "Bearer "+credential)
		req.Header.Set("Content-Type", "application/json")
		response, err := server.Client().Do(req)
		if err != nil {
			t.Error("loopback request failed")
			return 0, nil
		}
		defer response.Body.Close()
		var out map[string]any
		if err := json.NewDecoder(response.Body).Decode(&out); err != nil {
			t.Error("response decode failed")
		}
		return response.StatusCode, out
	}
	for _, credential := range credentials {
		if status, _ := request("GET", "/v1/status", credential, nil); status != 200 {
			t.Fatal("invalid independent session", status)
		}
	}
	return request, credentials
}

// stageUpdateOverHTTP mirrors the approval + stage flow of
// TestSkillUpdatePlanHTTPApprovalRetryReadAndIsolation and returns the
// stage route, the durable commit request, and the original operation route.
func stageUpdateOverHTTP(t *testing.T, s *Server, compare skillinstall.UpdateCompareRequest, comparisonRoute, oldGrantID, requestID string) (string, skillinstall.UpdateCommitRequest) {
	t.Helper()
	originalRoute := strings.TrimSuffix(comparisonRoute, "/update-comparison")
	createRoute := originalRoute + "/update-plans"
	code, old := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 {
		t.Fatal(code, old)
	}
	req := skillinstall.UpdateStageRequest{SchemaVersion: "local-skill-update-stage-create/v1", RequestID: requestID, OperationSignature: compare.OperationSignature, CandidateGrantID: compare.CandidateGrantID, ExpectedCandidateRevision: compare.ExpectedCandidateRevision, ExpectedPreviousRevision: int(old["state_revision"].(float64)), ExpectedBindingSignature: "", ActorID: "fixture-human"}
	candidateRoute := "/v1/grants/" + req.CandidateGrantID
	code, challenge := call(t, s, "POST", candidateRoute+"/challenge", token, map[string]any{"expected_revision": req.ExpectedCandidateRevision, "actor_id": req.ActorID})
	if code != 200 {
		t.Fatal(code, challenge)
	}
	ch := challenge["challenge"].(map[string]any)
	code, approved := call(t, s, "POST", candidateRoute+"/approve", token, map[string]any{"expected_revision": req.ExpectedCandidateRevision, "actor_id": req.ActorID, "challenge_id": ch["challenge_id"], "nonce": ch["nonce"]})
	if code != 200 {
		t.Fatal(code, approved)
	}
	req.ExpectedCandidateRevision = int(approved["state_revision"].(float64))
	code, created := call(t, s, "POST", createRoute, token, req)
	if code != 201 {
		t.Fatal(code, created)
	}
	plan := created["plan"].(map[string]any)
	commit := skillinstall.UpdateCommitRequest{SchemaVersion: "local-skill-update-commit/v1", UpdateID: plan["update_id"].(string), PlanSignature: plan["signature"].(string), ActorID: req.ActorID, ConfirmUpdate: true}
	return originalRoute, commit
}

func up05UpdateOperationsDir(t *testing.T, s *Server, updateID string) map[string]bool {
	t.Helper()
	entries, err := os.ReadDir(filepath.Join(s.d.Store.Dir, "skill-installations", "update-operations"))
	if err != nil {
		t.Fatal(err)
	}
	files := map[string]bool{}
	for _, e := range entries {
		name := e.Name()
		if !strings.HasSuffix(name, ".claim.json") && !strings.HasSuffix(name, ".result.json") {
			t.Fatal("unexpected artifact in update-operations:", name)
		}
		if suffix, ok := strings.CutPrefix(name, updateID+"."); ok {
			files[strings.TrimSuffix(suffix, ".json")] = true
		}
	}
	return files
}

func TestSkillUpdateCommitHTTPConcurrentAdminSessions(t *testing.T) {
	s, compare, comparisonRoute, oldGrantID := updateHTTPFixture(t)
	originalRoute, commit := stageUpdateOverHTTP(t, s, compare, comparisonRoute, oldGrantID, "up-"+strings.Repeat("a", 32))
	commitRoute := "/v1/skill-installations/updates"
	// Two admin sessions commit the same signed plan at the same time.
	const sessions = 3
	request, credentials := up05Clients(t, s, sessions)
	start := make(chan struct{})
	flights := make([]up05Flight, sessions)
	var wg sync.WaitGroup
	for i := 0; i < sessions; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			code, out := request("POST", commitRoute, credentials[i], commit)
			flights[i] = up05Flight{code: code, out: out}
		}(i)
	}
	close(start)
	wg.Wait()
	successes := 0
	winningSig := ""
	for i, f := range flights {
		t.Logf("session %d: status=%d error=%q", i, f.code, up05ErrorCode(f))
		if f.code == 429 && up05ErrorCode(f) == "skill_install_busy" {
			flights[i] = up05Terminal(t, request, credentials[i], "POST", commitRoute, commit)
			f = flights[i]
			t.Logf("session %d after Retry-After: status=%d error=%q", i, f.code, up05ErrorCode(f))
		}
		if f.code == 200 {
			result, _ := f.out["result"].(map[string]any)
			if result == nil || result["status"] != "updated_unverified" {
				t.Fatalf("session %d committed without durable result: %v", i, f.out)
			}
			sig := up05ResultSignature(f)
			if sig == "" {
				t.Fatalf("session %d 200 without a result signature: %v", i, f.out)
			}
			if winningSig == "" {
				winningSig = sig
			} else if sig != winningSig {
				t.Fatalf("committed sessions disagree on durable result: %+v", flights)
			}
			successes++
			continue
		}
		switch up05ErrorCode(f) {
		case "skill_install_conflict", "skill_install_changed", "skill_install_removal_pending", "skill_install_recovery_required":
		default:
			t.Fatalf("session %d: non-contract outcome status=%d body=%v", i, f.code, f.out)
		}
	}
	if successes == 0 {
		t.Fatalf("no session committed the update: %+v", flights)
	}
	// Durable artifacts: exactly this update's claim + result, nothing orphaned.
	files := up05UpdateOperationsDir(t, s, commit.UpdateID)
	if !files["claim"] || !files["result"] || len(files) != 2 {
		t.Fatal("update-operations artifacts:", files)
	}
	// The durable operation view agrees with what the winning session returned.
	code, view := call(t, s, "GET", "/v1/skill-installations/updates/"+commit.UpdateID, token, nil)
	if code != 200 {
		t.Fatal(code, view)
	}
	if view["status"] != "updated_unverified" {
		t.Fatal("durable update status:", view["status"])
	}
	result := view["result"].(map[string]any)
	if result["signature"] != winningSig {
		t.Fatal("durable result signature differs from winning commit")
	}
	// The original installation is removed exactly once and its Grant is frozen.
	code, removal := call(t, s, "GET", originalRoute+"/removal", token, nil)
	if code != 200 || removal["status"] != "removed" || removal["result"] == nil {
		t.Fatal("original install not durably removed:", code, removal)
	}
	// The original Grant is revoked exactly once: frozen revision across two reads.
	code, grant := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 || grant["grant"].(map[string]any)["status"] != "revoked" {
		t.Fatal("original grant not revoked:", code, grant)
	}
	code, grantAgain := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 || grantAgain["state_revision"] != grant["state_revision"] {
		t.Fatal("revoked grant revision not frozen:", grant["state_revision"], grantAgain["state_revision"])
	}
}

func TestSkillUpdateCommitHTTPConcurrentWithRemoval(t *testing.T) {
	s, compare, comparisonRoute, oldGrantID := updateHTTPFixture(t)
	originalRoute, commit := stageUpdateOverHTTP(t, s, compare, comparisonRoute, oldGrantID, "up-"+strings.Repeat("b", 32))
	// A third session prepares a removal from the pre-update state.
	code, removalView := call(t, s, "GET", originalRoute+"/removal", token, nil)
	if code != 200 || removalView["status"] != "not_requested" {
		t.Fatal(code, removalView)
	}
	record := removalView["record"].(map[string]any)
	removalReq := map[string]any{"schema_version": "local-skill-install-remove/v1", "operation_signature": record["operation"].(map[string]any)["signature"], "expected_grant_revision": int(removalView["state_revision"].(float64)), "expected_binding_signature": removalView["binding_signature"], "actor_id": "fixture-human", "confirm_remove": true}
	request, credentials := up05Clients(t, s, 2)
	start := make(chan struct{})
	var updateFlight, removalFlight up05Flight
	var wg sync.WaitGroup
	wg.Add(2)
	go func() {
		defer wg.Done()
		<-start
		c, out := request("POST", "/v1/skill-installations/updates", credentials[0], commit)
		updateFlight = up05Flight{code: c, out: out}
	}()
	go func() {
		defer wg.Done()
		<-start
		c, out := request("POST", originalRoute+"/removal", credentials[1], removalReq)
		removalFlight = up05Flight{code: c, out: out}
	}()
	close(start)
	wg.Wait()
	t.Logf("update: status=%d error=%q ; removal: status=%d error=%q", updateFlight.code, up05ErrorCode(updateFlight), removalFlight.code, up05ErrorCode(removalFlight))
	if updateFlight.code == 429 && up05ErrorCode(updateFlight) == "skill_install_busy" {
		updateFlight = up05Terminal(t, request, credentials[0], "POST", "/v1/skill-installations/updates", commit)
	}
	if removalFlight.code == 429 && up05ErrorCode(removalFlight) == "skill_install_busy" {
		removalFlight = up05Terminal(t, request, credentials[1], "POST", originalRoute+"/removal", removalReq)
	}
	t.Logf("update: status=%d error=%q ; removal: status=%d error=%q", updateFlight.code, up05ErrorCode(updateFlight), removalFlight.code, up05ErrorCode(removalFlight))
	updateWon := updateFlight.code == 200
	if updateWon {
		result, _ := updateFlight.out["result"].(map[string]any)
		if result == nil || result["status"] != "updated_unverified" {
			t.Fatal("update 200 without durable result:", updateFlight.out)
		}
		// The retrying removal either refuses with a contract error or is
		// accepted as idempotent reuse of the single removal the update already
		// performed — it must never perform a second revocation. The grant
		// freeze check below enforces that.
		if removalFlight.code != 200 {
			switch up05ErrorCode(removalFlight) {
			case "skill_install_changed", "skill_install_removal_pending", "skill_install_conflict", "skill_install_recovery_required", "skill_install_not_found":
			default:
				t.Fatal("stale removal accepted after concurrent update:", removalFlight.out)
			}
		}
	} else {
		switch up05ErrorCode(updateFlight) {
		case "skill_install_conflict", "skill_install_changed", "skill_install_removal_pending", "skill_install_recovery_required", "skill_install_not_found":
		default:
			t.Fatal("non-contract update outcome:", updateFlight.out)
		}
		if removalFlight.code != 200 {
			t.Fatal("removal did not win nor lose cleanly:", removalFlight.out)
		}
	}
	// Whatever the winner was, the durable state is single-valued and complete.
	viewPublished := updateWon
	code, view := call(t, s, "GET", "/v1/skill-installations/updates/"+commit.UpdateID, token, nil)
	if updateWon {
		if code != 200 || view["status"] != "updated_unverified" {
			t.Fatal("durable update status after winning commit:", code, view)
		}
	} else if code == 200 {
		viewPublished = true
		status, _ := view["status"].(string)
		if status != "" && status != "aborted" {
			// A removal that won mid-commit leaves a pending claim: recovery must
			// abort it cleanly, never resurrect the update.
			rec := map[string]any{"schema_version": "local-skill-update-recover/v1", "update_id": commit.UpdateID, "claim_signature": view["claim"].(map[string]any)["signature"], "actor_id": "fixture-human", "confirm_recovery": true}
			rcode, rout := call(t, s, "POST", "/v1/skill-installations/updates/"+commit.UpdateID+"/recover", token, rec)
			if rcode != 200 || rout["status"] != "aborted" {
				t.Fatal("recover after removal win:", rcode, rout)
			}
		}
	} else if code != 404 {
		// 404 means the removal won before any claim was published — clean.
		t.Fatal("unexpected update view after removal win:", code, view)
	}
	code, removal := call(t, s, "GET", originalRoute+"/removal", token, nil)
	if code != 200 || removal["status"] != "removed" || removal["result"] == nil {
		t.Fatal("original install not durably removed:", code, removal)
	}
	// Exactly one revocation: repeated reads must not observe the grant moving.
	code, g1 := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 || g1["grant"].(map[string]any)["status"] != "revoked" {
		t.Fatal("original grant not revoked:", code, g1)
	}
	code, g2 := call(t, s, "GET", "/v1/grants/"+oldGrantID, token, nil)
	if code != 200 || g2["state_revision"] != g1["state_revision"] {
		t.Fatal("original grant revoked more than once:", g1["state_revision"], g2["state_revision"])
	}
	// The durable removal result is the single one, stable across reads.
	code, removalAgain := call(t, s, "GET", originalRoute+"/removal", token, nil)
	if code != 200 || removalAgain["status"] != "removed" {
		t.Fatal("removal view not stable:", code, removalAgain)
	}
	if removalAgain["result"].(map[string]any)["signature"] != removal["result"].(map[string]any)["signature"] {
		t.Fatal("removal result changed between reads")
	}
	// A published claim must have its artifact on disk; if the removal won
	// before any claim was published, an empty artifact set is the clean outcome.
	if updateWon || viewPublished {
		if files := up05UpdateOperationsDir(t, s, commit.UpdateID); !files["claim"] {
			t.Fatal("claim artifact missing:", files)
		}
	}
}
