package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"reflect"
	"siq-agent-security/apps/agentshield/internal/state"
	"strconv"
	"strings"
	"testing"
)

func TestLocalUIRequiresMatchingHealthAndKeepsCredentialsOut(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("SIQ_AGENT_SECURITY_STATE_DIR", dir)
	st := &state.Store{Dir: dir}
	identity, err := st.DirectoryID()
	if err != nil {
		t.Fatal(err)
	}
	mode := "ready"
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/healthz/instance" || r.Header.Get("Authorization") != "" {
			t.Error("UI attempted credential access or pairing")
		}
		if mode == "redirect" {
			http.Redirect(w, r, "https://example.invalid", http.StatusFound)
			return
		}
		if mode == "html" {
			w.Header().Set("Content-Type", "text/html")
			_, _ = w.Write([]byte("<html/>"))
			return
		}
		id := identity
		if mode == "wrong" {
			id = strings.Repeat("0", 64)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(localHealth{SchemaVersion: "local-service-instance-health/v1", Product: "siq-agent-security", Version: "test", LocalMode: true, Status: "ready", StateDirectoryID: id})
	}))
	defer srv.Close()
	port := srv.Listener.Addr().(*net.TCPAddr).Port
	if err := cmdInitialize([]string{"--port", strconv.Itoa(port)}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	calls := 0
	failOpen := false
	opener := func(address string) error {
		calls++
		if address != srv.URL+"/" {
			t.Fatal("unexpected browser URL", address)
		}
		if failOpen {
			return errors.New("secret opener output")
		}
		return nil
	}
	for _, bad := range []string{"wrong", "redirect", "html"} {
		mode = bad
		var out bytes.Buffer
		if err := localUI(nil, &out, opener); err == nil || calls != 0 || out.Len() != 0 {
			t.Fatal("unverified page opened", bad, err)
		}
	}
	mode = "ready"
	var out bytes.Buffer
	if err := localUI([]string{"--print"}, &out, opener); err != nil || calls != 0 || out.String() != srv.URL+"/\n" {
		t.Fatal("print behavior", err)
	}
	out.Reset()
	if err := localUI(nil, &out, opener); err != nil || calls != 1 {
		t.Fatal("open behavior", err)
	}
	failOpen = true
	out.Reset()
	if err := localUI(nil, &out, opener); err == nil || strings.Contains(err.Error(), "secret") || out.String() != srv.URL+"/\n" {
		t.Fatal("browser failure did not preserve manual fallback", err)
	}
	if err := localUI([]string{"https://example.invalid"}, &out, opener); err == nil || calls != 2 {
		t.Fatal("arbitrary URL accepted")
	}
}
func TestBrowserCommandUsesDirectArgumentVector(t *testing.T) {
	address := "http://127.0.0.1:47611/"
	for _, tc := range []struct {
		platform, name string
		args           []string
	}{
		{"linux", "xdg-open", []string{address}},
		{"darwin", "open", []string{address}},
		{"windows", "rundll32.exe", []string{"url.dll,FileProtocolHandler", address}},
	} {
		name, args, err := browserCommand(tc.platform, address)
		if err != nil || name != tc.name || !reflect.DeepEqual(args, tc.args) {
			t.Fatal("wrong direct invocation", tc.platform)
		}
	}
	if _, _, err := browserCommand("unsupported", address); err == nil {
		t.Fatal("unsupported launcher accepted")
	}
}
