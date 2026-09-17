package server

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"siq-agent-security/apps/agentshield/internal/canon"
	"siq-agent-security/apps/agentshield/internal/hermeshome"
	"siq-agent-security/apps/agentshield/internal/skillinstall"
)

var (
	serverGitFixtureURL    = "https://git.example.com/org/skill.git"
	serverGitFixtureCommit = "c" + strings.Repeat("0", 39)
	serverZipFixtureURL    = "https://download.example.com/repo.zip"
	serverZipFixtureDigest = "d" + strings.Repeat("2", 63)
	serverLocatorFixture   = "e" + strings.Repeat("3", 63)
)

func serverHash(raw []byte) string {
	digest := sha256.Sum256(raw)
	return hex.EncodeToString(digest[:])
}

// updateSourceFixture applies an install whose import record can then be
// rewritten into a git or https_zip upstream shape without breaking the
// artifact binding the installed plan still links against.
func updateSourceFixture(t *testing.T) (*Server, string, string) {
	t.Helper()
	s, stage, importID := installPlanHTTPFixture(t, true)
	code, out := call(t, s, "POST", "/v1/skill-installations/plans", token, stage)
	if code != 201 {
		t.Fatal(code, out)
	}
	p := out["plan"].(map[string]any)
	req := skillinstall.ApplyRequest{SchemaVersion: "local-skill-install-apply/v1", PlanID: p["plan_id"].(string), PlanSignature: p["signature"].(string), ActorID: stage.ActorID, ConfirmInstall: true}
	code, installed := call(t, s, "POST", "/v1/skill-installations/apply", token, req)
	if code != 200 || installed["status"] != "installed_unverified" {
		t.Fatal(code, installed)
	}
	installID := strings.Replace(req.PlanID, "sip-", "sin-", 1)
	return s, importID, installID
}

func rewriteServerImportRecord(t *testing.T, s *Server, importID string, mutate func(map[string]any)) {
	t.Helper()
	path := filepath.Join(s.d.Store.Dir, "skill-imports", "records", importID+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	value, err := canon.Decode(raw)
	if err != nil {
		t.Fatal(err)
	}
	doc, ok := value.(map[string]any)
	if !ok {
		t.Fatal("record is not an object")
	}
	mutate(doc)
	delete(doc, "signature")
	signature, err := s.d.Key.SignCanonical(doc)
	if err != nil {
		t.Fatal(err)
	}
	doc["signature"] = signature
	signed, err := canon.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, signed, 0600); err != nil {
		t.Fatal(err)
	}
}

func gitifyServerImportRecord(t *testing.T, s *Server, importID string) {
	t.Helper()
	rewriteServerImportRecord(t, s, importID, func(doc map[string]any) {
		doc["schema_version"] = "local-skill-import/v2"
		doc["source_kind"] = "git"
		doc["git"] = map[string]any{"url": serverGitFixtureURL, "ref": "", "sub_dir": "", "expected_commit": "", "commit_sha": serverGitFixtureCommit}
		doc["excluded_git_metadata"] = true
		canonical, err := canon.Marshal(map[string]any{"url": serverGitFixtureURL, "ref": "", "sub_dir": "", "expected_commit": ""})
		if err != nil {
			t.Fatal(err)
		}
		doc["source_locator_digest"] = serverHash(canonical)
	})
}

func zipifyServerImportRecord(t *testing.T, s *Server, importID string) {
	t.Helper()
	rewriteServerImportRecord(t, s, importID, func(doc map[string]any) {
		doc["schema_version"] = "local-skill-import/v2"
		doc["source_kind"] = "https_zip"
		delete(doc, "git")
		doc["remote"] = map[string]any{"archive_sha256": serverZipFixtureDigest, "archive_bytes": 4096, "final_locator_digest": serverLocatorFixture, "archive_path": "", "expected_sha256": serverZipFixtureDigest}
		doc["excluded_git_metadata"] = true
		canonical, err := canon.Marshal(map[string]any{"url": serverZipFixtureURL, "archive_path": "", "expected_sha256": serverZipFixtureDigest})
		if err != nil {
			t.Fatal(err)
		}
		doc["source_locator_digest"] = serverHash(canonical)
	})
}

func updateSourceSaveBody(remoteURL string, enable bool) map[string]any {
	return map[string]any{"schema_version": "local-skill-update-source-save/v1", "remote_url": remoteURL, "enable": enable, "actor_id": "fixture-human"}
}

func updateSourceDisableBody() map[string]any {
	return map[string]any{"schema_version": "local-skill-update-source-disable/v1", "actor_id": "fixture-human"}
}

func updateSourceView(t *testing.T, value map[string]any) skillinstall.UpdateScheduleView {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	var view skillinstall.UpdateScheduleView
	if err := json.Unmarshal(raw, &view); err != nil {
		t.Fatal(err)
	}
	return view
}

func TestSkillUpdateSourceHTTPSaveViewAndDisable(t *testing.T) {
	s, _, installID := updateSourceFixture(t)
	route := "/v1/skill-installations/operations/" + installID + "/update-source"
	// A local_dir install has no fetchable upstream: the view says so and a
	// save is refused without writing schedule metadata.
	if code, out := call(t, s, "GET", route, token, nil); code != 200 || out["source_state"] != "unsupported" || out["status"] != "unsupported" || out["source_kind"] != "local_dir" {
		t.Fatal("local view", code, out)
	}
	if code, out := call(t, s, "POST", route, token, updateSourceSaveBody("", true)); code != 400 || out["error"] != "skill_install_invalid" {
		t.Fatal("local save accepted", code, out)
	}
	s2, importID, installID2 := updateSourceFixture(t)
	gitifyServerImportRecord(t, s2, importID)
	route = "/v1/skill-installations/operations/" + installID2 + "/update-source"
	code, saved := call(t, s2, "POST", route, token, updateSourceSaveBody("", true))
	if code != 200 {
		t.Fatal(code, saved)
	}
	view := updateSourceView(t, saved)
	if view.SchemaVersion != "local-skill-update-schedule-view/v1" || view.InstallID != installID2 || view.SourceKind != "git" || view.SourceState != "saved" || !view.Enabled || view.Status != "not_checked" || view.Display != serverGitFixtureURL || view.NextCheckAt == "" {
		t.Fatal("saved view", view)
	}
	// The schedule record internals (locator, binding digest, signature) must
	// never leak through the view.
	if raw, err := json.Marshal(saved); err != nil || strings.Contains(string(raw), "install_binding_digest") || strings.Contains(string(raw), "signature") {
		t.Fatal("view leaked schedule internals", err)
	}
	code, read := call(t, s2, "GET", route, token, nil)
	if code != 200 {
		t.Fatal(code, read)
	}
	if reread := updateSourceView(t, read); reread != view {
		t.Fatal("read diverged from save", reread)
	}
	code, disabled := call(t, s2, "POST", route, token, updateSourceSaveBody("", false))
	if code != 200 {
		t.Fatal(code, disabled)
	}
	if off := updateSourceView(t, disabled); off.Enabled || off.NextCheckAt != "" || off.SourceState != "saved" {
		t.Fatal("disable", off)
	}
	code, enabled := call(t, s2, "POST", route, token, updateSourceSaveBody("", true))
	if code != 200 {
		t.Fatal(code, enabled)
	}
	if on := updateSourceView(t, enabled); !on.Enabled || on.NextCheckAt == "" {
		t.Fatal("re-enable", on)
	}
}

func TestSkillUpdateSourceHTTPDisableSavedZIPWithoutLocator(t *testing.T) {
	s, importID, installID := updateSourceFixture(t)
	zipifyServerImportRecord(t, s, importID)
	sourceRoute := "/v1/skill-installations/operations/" + installID + "/update-source"
	disableRoute := sourceRoute + "/disable"

	if code, out := call(t, s, "POST", disableRoute, token, updateSourceDisableBody()); code != 409 || out["error"] != "skill_update_source_not_configured" {
		t.Fatal("missing saved source", code, out)
	}
	if code, out := call(t, s, "POST", sourceRoute, token, updateSourceSaveBody(serverZipFixtureURL, true)); code != 200 || out["enabled"] != true {
		t.Fatal("zip save", code, out)
	}
	code, out := call(t, s, "POST", disableRoute, token, updateSourceDisableBody())
	if code != 200 || out["enabled"] != false || out["source_state"] != "saved" || out["display"] != serverZipFixtureURL {
		t.Fatal("zip disable without locator", code, out)
	}
	// A retry after losing the first response returns the same disabled view.
	if code, replay := call(t, s, "POST", disableRoute, token, updateSourceDisableBody()); code != 200 || replay["enabled"] != false || replay["display"] != serverZipFixtureURL {
		t.Fatal("disable replay", code, replay)
	}

	for _, credential := range []string{"", token} {
		r := loopbackRequest("POST", disableRoute, updateSourceDisableBody())
		if credential != "" {
			r.Header.Set("Authorization", "Bearer "+credential)
		}
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		want := 401
		if credential != "" {
			want = 403
		}
		if w.Code != want {
			t.Fatal("disable capability", w.Code)
		}
	}
	if code, _ := call(t, s, "GET", disableRoute, token, nil); code != 405 {
		t.Fatal("disable method", code)
	}
	raw, _ := json.Marshal(updateSourceDisableBody())
	for _, bad := range []string{
		`{}`,
		strings.Replace(string(raw), `"actor_id":`, `"actor_id":"duplicate","actor_id":`, 1),
		strings.TrimSuffix(string(raw), "}") + `,"remote_url":"https://evil.example/redirect.zip"}`,
		strings.Replace(string(raw), `"local-skill-update-source-disable/v1"`, `"local-skill-update-source-disable/v2"`, 1),
	} {
		r := loopbackRequest("POST", disableRoute, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("strict disable body", w.Code, w.Body.String())
		}
	}
}

func TestSkillUpdateSourceHTTPValidationAndErrors(t *testing.T) {
	s, importID, installID := updateSourceFixture(t)
	gitifyServerImportRecord(t, s, importID)
	route := "/v1/skill-installations/operations/" + installID + "/update-source"
	for _, method := range []string{"GET", "POST"} {
		for _, credential := range []string{"", token} {
			r := loopbackRequest(method, route, nil)
			if method == "POST" {
				r = loopbackRequest(method, route, updateSourceSaveBody("", true))
			}
			if credential != "" {
				r.Header.Set("Authorization", "Bearer "+credential)
			}
			w := httptest.NewRecorder()
			s.Handler().ServeHTTP(w, r)
			want := 401
			if credential != "" {
				want = 403
			}
			if w.Code != want {
				t.Fatal("update-source capability", w.Code)
			}
		}
	}
	if code, _ := call(t, s, "DELETE", route, token, nil); code != 405 {
		t.Fatal("update-source method", code)
	}
	raw, _ := json.Marshal(updateSourceSaveBody("", true))
	for _, bad := range []string{
		`{}`,
		strings.Replace(string(raw), `"enable":true`, `"enable":null`, 1),
		strings.Replace(string(raw), `"actor_id":`, `"actor_id":"duplicate","actor_id":`, 1),
		strings.TrimSuffix(string(raw), "}") + `,"locator":"/escape"}`,
		strings.Replace(string(raw), `"local-skill-update-source-save/v1"`, `"local-skill-update-source-save/v2"`, 1),
	} {
		r := loopbackRequest("POST", route, bad)
		r.Header.Set("Authorization", "Bearer "+s.bootAdmin)
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		if w.Code != 400 {
			t.Fatal("strict body", w.Code, w.Body.String())
		}
	}
	// A git install keeps its URL in the signed record; a caller-supplied one
	// can never redirect the check.
	if code, out := call(t, s, "POST", route, token, updateSourceSaveBody(serverGitFixtureURL, true)); code != 400 {
		t.Fatal("git save with url accepted", code, out)
	}
	if code, out := call(t, s, "POST", "/v1/skill-installations/operations/sin-"+strings.Repeat("9", 64)+"/update-source", token, updateSourceSaveBody("", true)); code != 404 || out["error"] != "skill_install_not_found" {
		t.Fatal("unknown install", code, out)
	}
	if code, _ := call(t, s, "GET", route+"/extra", token, nil); code != 404 {
		t.Fatal("deep path", code)
	}
	// ZIP retention: the caller must re-provide the exact bound URL, query
	// strings are refused, and a wrong URL is a changed-source conflict.
	s2, zipID, zipInstall := updateSourceFixture(t)
	zipifyServerImportRecord(t, s2, zipID)
	zipRoute := "/v1/skill-installations/operations/" + zipInstall + "/update-source"
	// A query-string URL fails the binding digest first (the canonical covers
	// the full URL), so it can never be persisted either way.
	if code, out := call(t, s2, "POST", zipRoute, token, updateSourceSaveBody(serverZipFixtureURL+"?token=secret", true)); code != 409 || out["error"] != "skill_install_changed" {
		t.Fatal("query locator accepted", code, out)
	}
	if code, out := call(t, s2, "POST", zipRoute, token, updateSourceSaveBody("https://download.example.com/other.zip", true)); code != 409 || out["error"] != "skill_install_changed" {
		t.Fatal("wrong zip locator", code, out)
	}
	code, saved := call(t, s2, "POST", zipRoute, token, updateSourceSaveBody(serverZipFixtureURL, true))
	if code != 200 {
		t.Fatal(code, saved)
	}
	if view := updateSourceView(t, saved); view.SourceKind != "https_zip" || view.SourceState != "saved" || view.Display != serverZipFixtureURL {
		t.Fatal("zip view", view)
	}
	if raw, err := json.Marshal(saved); err != nil || strings.Contains(string(raw), "?") || strings.Contains(string(raw), "secret") {
		t.Fatal("locator leaked query or credentials", err)
	}
}

// TestSkillUpdateSourceHTTPRemovalPending is the TOCTOU combination: a source
// saved for a live install must become unreachable the moment removal starts —
// late schedule reads and writes never land on a removed install.
func TestSkillUpdateSourceHTTPRemovalPending(t *testing.T) {
	s, importID, installID := updateSourceFixture(t)
	gitifyServerImportRecord(t, s, importID)
	route := "/v1/skill-installations/operations/" + installID
	if code, out := call(t, s, "POST", route+"/update-source", token, updateSourceSaveBody("", true)); code != 200 {
		t.Fatal(code, out)
	}
	code, view := call(t, s, "GET", route+"/removal", token, nil)
	if code != 200 {
		t.Fatal(code, view)
	}
	code, installed := call(t, s, "GET", route, token, nil)
	if code != 200 {
		t.Fatal(code, installed)
	}
	req := skillinstall.RemoveRequest{SchemaVersion: "local-skill-install-remove/v1", OperationSignature: installed["operation"].(map[string]any)["signature"].(string), ExpectedGrantRevision: int(view["state_revision"].(float64)), ActorID: "fixture-human", ConfirmRemove: true}
	// A user-owned file keeps preflight from completing synchronously, holding
	// the install in cleanup_pending — the state a race hits in practice.
	plan := installed["plan"].(map[string]any)
	root, err := hermeshome.Resolve(s.hermesRoots(), plan["instance_id"].(string))
	if err != nil {
		t.Fatal(err)
	}
	userFile := filepath.Join(root.Path, "skills", plan["directory_name"].(string), "user.txt")
	if err := os.WriteFile(userFile, []byte("user owns this"), 0600); err != nil {
		t.Fatal(err)
	}
	if code, out := call(t, s, "POST", route+"/removal", token, req); code != 200 || out["status"] != "cleanup_pending" {
		t.Fatal("removal not pending", code, out)
	}
	if code, out := call(t, s, "GET", route+"/update-source", token, nil); code != 409 || out["error"] != "skill_install_removal_pending" {
		t.Fatal("view during removal", code, out)
	}
	if code, out := call(t, s, "POST", route+"/update-source", token, updateSourceSaveBody("", true)); code != 409 || out["error"] != "skill_install_removal_pending" {
		t.Fatal("save during removal", code, out)
	}
	if code, out := call(t, s, "POST", route+"/update-source/disable", token, updateSourceDisableBody()); code != 409 || out["error"] != "skill_install_removal_pending" {
		t.Fatal("disable during removal", code, out)
	}
}

// TestSkillUpdateComparisonHTTPTruncates210FileCandidate drives the explicit
// update-comparison flow over a real 210-file candidate: every change is
// counted, only the first 200 are returned, and the truncation flag matches
// the total the panel validates against.
func TestSkillUpdateComparisonHTTPTruncates210FileCandidate(t *testing.T) {
	s, compare, comparisonRoute, grantID := updateHTTPFixture(t)
	installedRoute := strings.TrimSuffix(comparisonRoute, "/update-comparison")
	code, installed := call(t, s, "GET", installedRoute, token, nil)
	if code != 200 {
		t.Fatal(code, installed)
	}
	// The candidate keeps the installed SKILL.md byte-identical and adds 210
	// genuinely new files: the total stays honest at 210 while the payload is
	// capped at the 200-item inspection bound.
	candidate := t.TempDir()
	skill := "---\nname: http-import\ndescription: Read a synthetic report.\n---\nRead a report.\n"
	if err := os.WriteFile(filepath.Join(candidate, "SKILL.md"), []byte(skill), 0600); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 210; i++ {
		name := filepath.Join(candidate, fmt.Sprintf("gen-%03d.md", i))
		if err := os.WriteFile(name, []byte("generated change "+fmt.Sprintf("%03d", i)+"\n"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	code, imported := call(t, s, "POST", "/v1/skill-imports", token, map[string]any{"schema_version": "local-skill-import-create/v1", "import_id": "si-" + strings.Repeat("d", 32), "source_kind": "local_dir", "path": candidate, "actor_id": "fixture-human"})
	if code != 201 {
		t.Fatal(code, imported)
	}
	big := imported["import"].(map[string]any)
	code, permission := call(t, s, "POST", "/v1/skill-imports/"+big["import_id"].(string)+"/permissions", token, map[string]any{"schema_version": "local-skill-import-permission-create/v1", "request_id": "ip-" + strings.Repeat("e", 32), "artifact_digest": big["artifact_digest"], "analysis_sha256": big["analysis_sha256"], "instance_id": installed["plan"].(map[string]any)["instance_id"], "actor_id": "fixture-human"})
	if code != 201 {
		t.Fatal(code, permission)
	}
	compare.CandidateGrantID = permission["grant"].(map[string]any)["grant_id"].(string)
	compare.ExpectedCandidateRevision = int(permission["state_revision"].(float64))
	code, out := call(t, s, "POST", comparisonRoute, token, compare)
	if code != 200 {
		t.Fatal(code, out)
	}
	raw, err := json.Marshal(out)
	if err != nil {
		t.Fatal(err)
	}
	var comparison skillinstall.UpdateComparison
	if err := json.Unmarshal(raw, &comparison); err != nil {
		t.Fatal(err)
	}
	if comparison.ContentChangesTotal != 210 || len(comparison.ContentChanges) != 200 || !comparison.ContentChangesTruncated || !comparison.RequiresConfirmation {
		t.Fatal("210-item truncation", comparison.ContentChangesTotal, len(comparison.ContentChanges), comparison.ContentChangesTruncated, comparison.RequiresConfirmation)
	}
	current, _, err := s.d.Store.GetGrantWithSeq(grantID)
	if err != nil || current.Status != "approved" {
		t.Fatal("old grant changed", err)
	}
}
