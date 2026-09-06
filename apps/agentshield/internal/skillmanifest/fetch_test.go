package skillmanifest

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
)

func TestSelectArtifact(t *testing.T) {
	arts := []Artifact{
		{OS: "linux", Arch: "amd64", SHA256: strings.Repeat("ab", 32), URL: "https://example/x"},
		{OS: "darwin", Arch: "arm64", SHA256: strings.Repeat("cd", 32), URL: "https://example/y"},
	}
	got, err := SelectArtifact(arts, "darwin", "arm64")
	if err != nil || got.URL != "https://example/y" {
		t.Fatalf("got=%+v err=%v", got, err)
	}
	if _, err := SelectArtifact(arts, "windows", "amd64"); err == nil {
		t.Fatal("missing platform must fail")
	}
}

func TestDownloadVerifiedArtifactHappyAndNegatives(t *testing.T) {
	payload := []byte("#!/bin/sh\necho fetch-ok\n")
	sum := sha256.Sum256(payload)
	pin := hex.EncodeToString(sum[:])
	n := len(payload)

	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/ok":
			w.Header().Set("Content-Length", strconv.Itoa(n))
			_, _ = w.Write(payload)
		case "/wronghash":
			body := []byte("#!/bin/sh\necho other\n")
			w.Header().Set("Content-Length", strconv.Itoa(len(body)))
			_, _ = w.Write(body)
		case "/toobig":
			body := append(append([]byte{}, payload...), 0, 1, 2, 3)
			w.Header().Set("Content-Length", strconv.Itoa(len(body)))
			_, _ = w.Write(body)
		case "/clmismatch":
			w.Header().Set("Content-Length", "99")
			_, _ = w.Write(payload)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()

	dir := t.TempDir()
	opts := FetchOptions{AllowInsecureHTTP: true}

	artOK := Artifact{
		OS: "linux", Arch: "amd64",
		SHA256: pin, URL: srv.URL + "/ok", Bytes: int64(n),
	}
	dest := filepath.Join(dir, "bin")
	got, err := DownloadVerifiedArtifact(context.Background(), artOK, dest, opts)
	if err != nil || got != pin {
		t.Fatalf("happy: digest=%s err=%v", got, err)
	}
	st, err := os.Stat(dest)
	if err != nil || st.Mode().Perm()&0o100 == 0 {
		t.Fatalf("downloaded must be executable: mode=%v err=%v", st.Mode(), err)
	}

	if _, err := DownloadVerifiedArtifact(context.Background(), artOK, filepath.Join(dir, "no"), FetchOptions{}); err == nil {
		t.Fatal("http without AllowInsecureHTTP must fail")
	}

	artBad := artOK
	artBad.URL = srv.URL + "/wronghash"
	artBad.Bytes = int64(len([]byte("#!/bin/sh\necho other\n")))
	if _, err := DownloadVerifiedArtifact(context.Background(), artBad, filepath.Join(dir, "bad"), opts); err == nil {
		t.Fatal("wrong hash must fail")
	}

	artBig := artOK
	artBig.URL = srv.URL + "/toobig"
	artBig.Bytes = int64(n)
	if _, err := DownloadVerifiedArtifact(context.Background(), artBig, filepath.Join(dir, "big"), opts); err == nil {
		t.Fatal("oversized vs pin must fail")
	}

	artCL := artOK
	artCL.URL = srv.URL + "/clmismatch"
	if _, err := DownloadVerifiedArtifact(context.Background(), artCL, filepath.Join(dir, "cl"), opts); err == nil {
		t.Fatal("Content-Length mismatch must fail")
	}
}

func TestFetchAndStage(t *testing.T) {
	payload := []byte("#!/bin/sh\necho staged\n")
	sum := sha256.Sum256(payload)
	pin := hex.EncodeToString(sum[:])
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", strconv.Itoa(len(payload)))
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	dir := t.TempDir()
	art := Artifact{
		SHA256: pin,
		URL:    srv.URL + "/siq-agent-security-linux-amd64",
		Bytes:  int64(len(payload)),
	}
	staged, err := FetchAndStage(context.Background(), art, filepath.Join(dir, "stage"), FetchOptions{AllowInsecureHTTP: true})
	if err != nil {
		t.Fatal(err)
	}
	got, err := HashFileDigest(staged)
	if err != nil || got != pin {
		t.Fatalf("staged digest %s want %s err=%v", got, pin, err)
	}
}

func TestPythonFetchArtifact(t *testing.T) {
	dir, err := FindSkillDir()
	if err != nil {
		t.Skip(err)
	}
	py := filepath.Join(dir, "scripts", "verify_manifest.py")
	payload := []byte("#!/bin/sh\necho py-fetch\n")
	sum := sha256.Sum256(payload)
	pin := hex.EncodeToString(sum[:])
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", strconv.Itoa(len(payload)))
		_, _ = w.Write(payload)
	}))
	defer srv.Close()

	arts := fakeArtifacts()
	for i := range arts {
		if arts[i].OS == runtime.GOOS && arts[i].Arch == runtime.GOARCH {
			arts[i].SHA256 = pin
			arts[i].URL = srv.URL + "/siq-agent-security"
			arts[i].Bytes = int64(len(payload))
		}
	}
	// Platforms without a Targets entry still need a pin for select_artifact on this host.
	found := false
	for _, a := range arts {
		if a.OS == runtime.GOOS && a.Arch == runtime.GOARCH {
			found = true
			break
		}
	}
	if !found {
		arts = append(arts, Artifact{
			OS: runtime.GOOS, Arch: runtime.GOARCH,
			SHA256: pin, URL: srv.URL + "/siq-agent-security", Bytes: int64(len(payload)),
		})
	}

	k := testKey(t)
	m, err := Build(Options{ContentHash: strings.Repeat("cd", 32), Artifacts: arts, SignedBy: k.PublicBase64()})
	if err != nil {
		t.Fatal(err)
	}
	if err := Sign(m, k); err != nil {
		t.Fatal(err)
	}
	tmp := filepath.Join(t.TempDir(), "skill-manifest.json")
	if err := WriteFile(tmp, m); err != nil {
		t.Fatal(err)
	}
	stage := t.TempDir()
	cmd := exec.Command("python3", py,
		"--manifest", tmp, "--pubkey", k.PublicBase64(),
		"--fetch-artifact", "--stage-to", stage,
	)
	cmd.Env = append(os.Environ(), "SIQ_AGENT_SECURITY_ALLOW_INSECURE_DOWNLOAD=1")
	out, err := cmd.CombinedOutput()
	if err != nil {
		t.Fatalf("python fetch failed: %v\n%s", err, out)
	}
	lines := strings.Split(strings.TrimSpace(string(out)), "\n")
	path := ""
	for i := len(lines) - 1; i >= 0; i-- {
		l := strings.TrimSpace(lines[i])
		if l != "" && !strings.Contains(l, "siq-agent-security-verify") {
			path = l
			break
		}
	}
	if path == "" || !strings.HasPrefix(path, stage) {
		t.Fatalf("expected staged path under %s, got %q\n%s", stage, path, out)
	}
	got, err := HashFileDigest(path)
	if err != nil || got != pin {
		t.Fatalf("staged digest %s want %s err=%v", got, pin, err)
	}
}
