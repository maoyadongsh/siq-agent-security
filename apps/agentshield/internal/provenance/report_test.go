package provenance

import (
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestReportCeilingPrivacyRetryAndExpiry(t *testing.T) {
	a, _, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	source := Source{Type: "MCP", SourceID: "private-endpoint-fixture"}
	content := "sensitive-fixture-content"
	expires := now.Add(time.Hour)
	first, err := s.Report("report-1", source, a.Scope, content, expires, now)
	if err != nil {
		t.Fatal(err)
	}
	if first.Source.Trust != "untrusted" || first.Source.SourceID == source.SourceID {
		t.Fatal("unprivileged report trusted or raw identity persisted")
	}
	again, err := s.Report("report-1", source, a.Scope, content, expires, now.Add(time.Second))
	if err != nil || first.Signature != again.Signature {
		t.Fatal("retry changed assertion", err)
	}
	if _, err := s.Report("report-1", source, a.Scope, "changed", expires, now); err == nil {
		t.Fatal("report conflict overwrote content")
	}
	if _, err := s.Report("report-1", source, a.Scope, content, expires, now.Add(16*time.Minute)); err == nil {
		t.Fatal("expired report silently renewed")
	}
	for _, bad := range []Source{{Type: "USER", SourceID: "caller", Trust: "authoritative"}, {Type: "TRUSTED_IAM", SourceID: "caller", Trust: "untrusted"}, {Type: "MCP", SourceID: "caller", Trust: "trusted"}} {
		if _, err := s.Report("forged", bad, a.Scope, content, expires, now); err == nil {
			t.Fatal("caller elevated source", bad)
		}
	}
	err = filepath.WalkDir(s.dir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		raw, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		if strings.Contains(string(raw), content) || strings.Contains(string(raw), source.SourceID) {
			t.Error("raw report leaked to storage")
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
func TestConcurrentReportRetriesUseOneAssertion(t *testing.T) {
	a, _, key, now := authorityFixture(t)
	s, err := Open(t.TempDir(), key)
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	signatures := make(chan string, 16)
	for n := 0; n < 16; n++ {
		wg.Add(1)
		go func(n int) {
			defer wg.Done()
			r, err := s.Report("same-id", Source{Type: "MCP", SourceID: "endpoint"}, a.Scope, "value", now.Add(time.Hour), now.Add(time.Duration(n)*time.Millisecond))
			if err != nil {
				t.Error(err)
				return
			}
			signatures <- r.Signature
		}(n)
	}
	wg.Wait()
	close(signatures)
	signature := ""
	for got := range signatures {
		if signature != "" && got != signature {
			t.Fatal("concurrent retry diverged")
		}
		signature = got
	}
}
