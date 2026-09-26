//go:build linux

package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

const pendingListTestSecret = "synthetic-pending-secret"

// A device-side discovery client is always constructed from the local identity,
// so tests build one the same way the CLI does.
func pendingListClient(server, identity string) *Client {
	return NewClient(ClientConfig{ControlPlaneURL: server, DeviceIdentity: identity, Secret: pendingListTestSecret})
}

type pendingListRequest struct {
	method string
	target string
	auth   string
	ident  string
}

// A recording server: discovery must only ever issue authenticated GETs, so the
// request log is part of the assertion rather than a debugging aid.
type pendingListServer struct {
	*httptest.Server
	mu       sync.Mutex
	requests []pendingListRequest
	pages    []http.HandlerFunc
	status   int
}

func newPendingListServer(t *testing.T) *pendingListServer {
	t.Helper()
	s := &pendingListServer{status: http.StatusOK}
	s.Server = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.requests = append(s.requests, pendingListRequest{r.Method, r.URL.RequestURI(), r.Header.Get("Authorization"), r.Header.Get("X-Edge-Identity")})
		index := len(s.requests) - 1
		status := s.status
		var page http.HandlerFunc
		if index < len(s.pages) {
			page = s.pages[index]
		}
		s.mu.Unlock()
		if status != http.StatusOK {
			w.WriteHeader(status)
			return
		}
		if page == nil {
			w.Header().Set("Content-Type", "application/json")
			w.Write(pendingListWire(t, nil, nil, nil))
			return
		}
		page(w, r)
	}))
	t.Cleanup(s.Close)
	return s
}

func (s *pendingListServer) setPages(pages ...http.HandlerFunc) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.pages = pages
}

func (s *pendingListServer) log() []pendingListRequest {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]pendingListRequest(nil), s.requests...)
}

func stringPtr(value string) *string { return &value }

func jsonPage(t *testing.T, body []byte) http.HandlerFunc {
	return func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if _, err := w.Write(body); err != nil {
			t.Error(err)
		}
	}
}

// pendingListWire renders the frozen response shape. next_cursor is null unless
// a cursor is supplied, matching the endpoint's last-page projection.
func pendingListWire(t *testing.T, items []map[string]any, integrity []string, cursor *string) []byte {
	t.Helper()
	if items == nil {
		items = []map[string]any{}
	}
	if integrity == nil {
		integrity = []string{}
	}
	var next any
	if cursor != nil {
		next = *cursor
	}
	raw, err := json.Marshal(map[string]any{
		"schema_version":   "enterprise-discovery-schedule-pending-list/v1",
		"evaluated_at":     "2026-09-26T00:00:00.123456Z",
		"items":            items,
		"integrity_failed": integrity,
		"next_cursor":      next,
	})
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func pendingListItem(t *testing.T, intent DiscoverySchedule, digest string) map[string]any {
	t.Helper()
	raw, err := json.Marshal(intent)
	if err != nil {
		t.Fatal(err)
	}
	var encoded map[string]any
	if json.Unmarshal(raw, &encoded) != nil {
		t.Fatal("intent fixture")
	}
	return map[string]any{"schedule_id": intent.ID, "status": "pending_confirmation",
		"revision": 0, "intent": encoded, "intent_digest": digest}
}

func pendingScheduleID(seed int) string { return fmt.Sprintf("eds-%032x", seed) }

func TestPendingScheduleDiscoveryRejectsUntrustedPages(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	digest, err := base.digest()
	if err != nil {
		t.Fatal(err)
	}
	valid := pendingListItem(t, base, digest)
	clone := func(mutate func(map[string]any)) map[string]any {
		raw, _ := json.Marshal(valid)
		var copy map[string]any
		if json.Unmarshal(raw, &copy) != nil {
			t.Fatal("item fixture")
		}
		mutate(copy)
		return copy
	}
	topLevel := func(mutate func(map[string]any)) []byte {
		var page map[string]any
		if json.Unmarshal(pendingListWire(t, []map[string]any{valid}, nil, nil), &page) != nil {
			t.Fatal("page fixture")
		}
		mutate(page)
		raw, err := json.Marshal(page)
		if err != nil {
			t.Fatal(err)
		}
		return raw
	}

	for _, mode := range []struct {
		name string
		body []byte
	}{
		{"top_extra_field", topLevel(func(page map[string]any) { page["extra"] = true })},
		{"top_missing_field", topLevel(func(page map[string]any) { delete(page, "integrity_failed") })},
		{"top_null_items", topLevel(func(page map[string]any) { page["items"] = nil })},
		{"schema_version", topLevel(func(page map[string]any) { page["schema_version"] = "enterprise-discovery-schedule-pending-list/v2" })},
		{"evaluated_at_garbage", topLevel(func(page map[string]any) { page["evaluated_at"] = "2026-09-26 00:00:00" })},
		{"evaluated_at_offset", topLevel(func(page map[string]any) { page["evaluated_at"] = "2026-09-26T08:00:00+08:00" })},
		{"evaluated_at_impossible", topLevel(func(page map[string]any) { page["evaluated_at"] = "2026-02-30T00:00:00Z" })},
		{"item_extra_field", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["extra"] = true })}, nil, nil)},
		{"item_missing_field", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { delete(item, "revision") })}, nil, nil)},
		{"item_null_revision", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["revision"] = nil })}, nil, nil)},
		{"item_null_digest", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["intent_digest"] = nil })}, nil, nil)},
		{"item_schedule_id_shape", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["schedule_id"] = "eds-XYZ" })}, nil, nil)},
		{"item_schedule_id_mismatch", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["schedule_id"] = pendingScheduleID(9) })}, nil, nil)},
		{"item_status_not_pending", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["status"] = "active" })}, nil, nil)},
		{"item_status_unknown", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["status"] = "weird" })}, nil, nil)},
		{"item_revision_negative", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["revision"] = -1 })}, nil, nil)},
		{"item_revision_already_advanced", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["revision"] = 1 })}, nil, nil)},
		{"item_revision_string", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["revision"] = "0" })}, nil, nil)},
		{"item_digest_mismatch", pendingListWire(t, []map[string]any{clone(func(item map[string]any) { item["intent_digest"] = strings.Repeat("f", 64) })}, nil, nil)},
		{"item_intent_extra", pendingListWire(t, []map[string]any{clone(func(item map[string]any) {
			item["intent"].(map[string]any)["extra"] = 1
		})}, nil, nil)},
		{"item_intent_other_device", pendingListWire(t, []map[string]any{clone(func(item map[string]any) {
			item["intent"].(map[string]any)["device_identity"] = "other-device"
		})}, nil, nil)},
		{"item_intent_purpose", pendingListWire(t, []map[string]any{clone(func(item map[string]any) {
			item["intent"].(map[string]any)["purpose"] = "scan_only"
		})}, nil, nil)},
		{"integrity_entry_not_an_id", pendingListWire(t, nil, []string{"../../etc/passwd"}, nil)},
		{"cursor_invalid_shape", pendingListWire(t, nil, nil, stringPtr("next-page"))},
		{"cursor_not_an_id_case", pendingListWire(t, nil, nil, stringPtr("eds-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"))},
	} {
		t.Run(mode.name, func(t *testing.T) {
			server := newPendingListServer(t)
			server.setPages(jsonPage(t, mode.body))
			found, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
			if err == nil {
				t.Fatal("untrusted page accepted")
			}
			if len(found.Candidates) != 0 {
				t.Fatal("untrusted candidates surfaced")
			}
		})
	}
}

func TestPendingScheduleDiscoveryRejectsMalformedBodies(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	for _, mode := range []struct {
		name string
		body []byte
	}{
		{"invalid_json", []byte("{")},
		{"trailing_json", append(pendingListWire(t, nil, nil, nil), []byte(" {}")...)},
		{"duplicate_top_key", append([]byte(`{"schema_version":"enterprise-discovery-schedule-pending-list/v1",`), pendingListWire(t, nil, nil, nil)[1:]...)},
		{"oversized", append(append([]byte(`{"schema_version":"`), bytes.Repeat([]byte("a"), pendingListPageBytes)...), []byte(`"}`)...)},
		{"empty", []byte{}},
	} {
		t.Run(mode.name, func(t *testing.T) {
			server := newPendingListServer(t)
			server.setPages(jsonPage(t, mode.body))
			if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background()); err == nil {
				t.Fatal("malformed body accepted")
			}
		})
	}
}

func TestPendingScheduleDiscoveryStatusAndNetworkFailures(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	for _, status := range []int{http.StatusUnauthorized, http.StatusNotFound, http.StatusConflict, http.StatusInternalServerError, http.StatusFound} {
		t.Run(fmt.Sprintf("status_%d", status), func(t *testing.T) {
			server := newPendingListServer(t)
			server.status = status
			if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background()); err == nil {
				t.Fatal("non-200 accepted")
			}
		})
	}
	t.Run("network_failure", func(t *testing.T) {
		client := pendingListClient("http://127.0.0.1:1", base.Identity)
		if _, err := client.discoverPendingSchedules(context.Background()); err == nil {
			t.Fatal("unreachable control plane accepted")
		}
	})
	t.Run("redirect_not_followed", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Location", "/must-not-follow")
			w.WriteHeader(http.StatusTemporaryRedirect)
		}))
		defer server.Close()
		if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background()); err == nil {
			t.Fatal("redirect followed")
		}
	})
	t.Run("missing_local_identity", func(t *testing.T) {
		server := newPendingListServer(t)
		for _, client := range []*Client{
			pendingListClient(server.URL, ""),
			NewClient(ClientConfig{ControlPlaneURL: server.URL, DeviceIdentity: base.Identity}),
		} {
			if _, err := client.discoverPendingSchedules(context.Background()); err == nil {
				t.Fatal("client without local identity enumerated")
			}
		}
		if len(server.log()) != 0 {
			t.Fatal("request sent without local identity")
		}
	})
}

func TestPendingScheduleDiscoveryBounds(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	digest, err := base.digest()
	if err != nil {
		t.Fatal(err)
	}

	t.Run("item_cap", func(t *testing.T) {
		var items []map[string]any
		for i := 0; i < pendingListMaxItems+1; i++ {
			intent := base
			intent.ID = pendingScheduleID(i)
			itemDigest, err := intent.digest()
			if err != nil {
				t.Fatal(err)
			}
			items = append(items, pendingListItem(t, intent, itemDigest))
		}
		server := newPendingListServer(t)
		server.setPages(jsonPage(t, pendingListWire(t, items, nil, nil)))
		found, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
		if err == nil || !strings.Contains(err.Error(), "pending_schedule_result_too_large") {
			t.Fatalf("item cap not enforced: %v", err)
		}
		// An over-large result is refused, not trimmed: nothing is offered for
		// selection and no further page is requested.
		if len(found.Candidates) != 0 {
			t.Fatalf("candidates=%d", len(found.Candidates))
		}
		if len(server.log()) != 1 {
			t.Fatal("item cap continued paging")
		}
	})

	t.Run("page_cap", func(t *testing.T) {
		server := newPendingListServer(t)
		pages := make([]http.HandlerFunc, 0, pendingListMaxPages+2)
		for i := 0; i < pendingListMaxPages+2; i++ {
			// Every page contains the exact row named by its advancing cursor:
			// only the page budget can stop this otherwise valid sequence.
			intent := base
			intent.ID = pendingScheduleID(i + 1)
			itemDigest, err := intent.digest()
			if err != nil {
				t.Fatal(err)
			}
			cursor := intent.ID
			pages = append(pages, jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, intent, itemDigest)}, nil, &cursor)))
		}
		server.setPages(pages...)
		_, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
		if err == nil || !strings.Contains(err.Error(), "pending_schedule_result_too_large") {
			t.Fatalf("page cap not enforced: %v", err)
		}
		if len(server.log()) != pendingListMaxPages {
			t.Fatalf("requests=%d", len(server.log()))
		}
	})

	for _, cursorMode := range []struct {
		name   string
		second string
	}{
		{"cursor_repeats", pendingScheduleID(1)},
		{"cursor_rewinds", pendingScheduleID(0)},
	} {
		t.Run(cursorMode.name, func(t *testing.T) {
			server := newPendingListServer(t)
			first := pendingScheduleID(1)
			second := cursorMode.second
			firstIntent := base
			firstIntent.ID = first
			firstDigest, err := firstIntent.digest()
			if err != nil {
				t.Fatal(err)
			}
			secondIntent := base
			secondIntent.ID = pendingScheduleID(2)
			secondDigest, err := secondIntent.digest()
			if err != nil {
				t.Fatal(err)
			}
			server.setPages(
				jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, firstIntent, firstDigest)}, nil, &first)),
				jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, secondIntent, secondDigest)}, nil, &second)),
			)
			if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background()); err == nil {
				t.Fatal("non-advancing cursor accepted")
			}
			if len(server.log()) != 2 {
				t.Fatal("non-advancing cursor kept paging")
			}
		})
	}

	t.Run("items_must_be_sorted_after_the_request_cursor", func(t *testing.T) {
		firstIntent := base
		firstIntent.ID = pendingScheduleID(2)
		firstDigest, err := firstIntent.digest()
		if err != nil {
			t.Fatal(err)
		}
		secondIntent := base
		secondIntent.ID = pendingScheduleID(1)
		secondDigest, err := secondIntent.digest()
		if err != nil {
			t.Fatal(err)
		}
		server := newPendingListServer(t)
		server.setPages(jsonPage(t, pendingListWire(t, []map[string]any{
			pendingListItem(t, firstIntent, firstDigest),
			pendingListItem(t, secondIntent, secondDigest),
		}, nil, nil)))
		if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background()); err == nil {
			t.Fatal("out-of-order items accepted")
		}
	})

	t.Run("second_page_failure_is_not_a_partial_list", func(t *testing.T) {
		cursor := base.ID
		server := newPendingListServer(t)
		server.setPages(
			jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, base, digest)}, nil, &cursor)),
			func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusInternalServerError) },
		)
		found, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
		if err == nil {
			t.Fatal("failed page treated as a complete list")
		}
		if len(found.Candidates) != 0 {
			t.Fatal("partial page surfaced as a candidate list")
		}
	})
}

func TestPendingScheduleDiscoveryIntegrityFailsClosed(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	digest, err := base.digest()
	if err != nil {
		t.Fatal(err)
	}
	broken := pendingScheduleID(7)
	other := pendingScheduleID(8)

	for _, mode := range []struct {
		name    string
		body    []byte
		wantIDs []string
	}{
		{"integrity_alone", pendingListWire(t, nil, []string{broken}, nil), []string{broken}},
		{"integrity_on_truncated_page", pendingListWire(t, nil, []string{broken}, &broken), []string{broken}},
		{"integrity_with_valid_item", pendingListWire(t, []map[string]any{pendingListItem(t, base, digest)}, []string{other}, nil), []string{other}},
	} {
		t.Run(mode.name, func(t *testing.T) {
			server := newPendingListServer(t)
			server.setPages(jsonPage(t, mode.body))
			found, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
			if err == nil || !strings.Contains(err.Error(), "pending_schedule_integrity_failed") {
				t.Fatalf("integrity failure not reported: %v", err)
			}
			if strings.Join(found.IntegrityFailed, ",") != strings.Join(mode.wantIDs, ",") {
				t.Fatalf("integrity IDs=%v", found.IntegrityFailed)
			}
			// A valid sibling never rescues the page into an auto-selection.
			if len(found.Candidates) != 0 {
				t.Fatal("candidate surfaced despite integrity failure")
			}
		})
	}
}

func TestPendingScheduleDiscoveryReadsOnlyGets(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	digest, err := base.digest()
	if err != nil {
		t.Fatal(err)
	}
	cursor := base.ID
	server := newPendingListServer(t)
	server.setPages(
		jsonPage(t, pendingListWire(t, []map[string]any{pendingListItem(t, base, digest)}, nil, &cursor)),
		jsonPage(t, pendingListWire(t, nil, nil, nil)),
	)
	found, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if len(found.Candidates) != 1 || found.Candidates[0].ID != base.ID || found.Candidates[0].Digest != digest ||
		found.Candidates[0].Status != "pending_confirmation" || found.Candidates[0].StartsAt != base.StartsAt ||
		found.Candidates[0].ExpiresAt != base.ExpiresAt {
		t.Fatalf("candidate projection changed: %+v", found.Candidates)
	}
	if parsed, err := parseDiscoverySchedule(found.Candidates[0].Intent); err != nil || *parsed != base {
		t.Fatal("candidate intent bytes changed")
	}
	if found.EvaluatedAt != "2026-09-26T00:00:00.123456Z" {
		t.Fatalf("evaluated_at=%q", found.EvaluatedAt)
	}
	requests := server.log()
	if len(requests) != 2 {
		t.Fatalf("requests=%d", len(requests))
	}
	for _, request := range requests {
		if request.method != http.MethodGet {
			t.Fatalf("non-GET discovery request: %s %s", request.method, request.target)
		}
		if request.auth != "Bearer "+pendingListTestSecret || request.ident != base.Identity {
			t.Fatal("discovery request missing device credentials")
		}
	}
	if !strings.Contains(requests[0].target, "limit=100") {
		t.Fatalf("page limit missing: %s", requests[0].target)
	}
	if strings.Contains(requests[0].target, "cursor=") || !strings.Contains(requests[1].target, "cursor="+cursor) {
		t.Fatalf("cursor handling changed: %v", requests)
	}
}

func TestPendingScheduleDiscoveryHonoursCancellation(t *testing.T) {
	_, base, _ := scheduleFixture(t)
	page := pendingListWire(t, nil, nil, nil)

	t.Run("before_request", func(t *testing.T) {
		server := newPendingListServer(t)
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		if _, err := pendingListClient(server.URL, base.Identity).discoverPendingSchedules(ctx); err == nil {
			t.Fatal("pre-cancelled discovery succeeded")
		}
		if len(server.log()) != 0 {
			t.Fatal("request sent after cancellation")
		}
	})

	t.Run("during_request", func(t *testing.T) {
		client := pendingListClient("http://127.0.0.1:1", base.Identity)
		ctx, cancel := context.WithCancel(context.Background())
		client.http.Transport = scheduleReadTransport(func(r *http.Request) (*http.Response, error) {
			cancel()
			return nil, r.Context().Err()
		})
		if _, err := client.discoverPendingSchedules(ctx); err == nil {
			t.Fatal("cancelled request succeeded")
		}
	})

	t.Run("after_response", func(t *testing.T) {
		client := pendingListClient("http://127.0.0.1:1", base.Identity)
		ctx, cancel := context.WithCancel(context.Background())
		defer cancel()
		client.http.Transport = scheduleReadTransport(func(*http.Request) (*http.Response, error) {
			cancel()
			return &http.Response{StatusCode: http.StatusOK, Body: io.NopCloser(bytes.NewReader(page)), Header: make(http.Header)}, nil
		})
		if _, err := client.discoverPendingSchedules(ctx); err == nil {
			t.Fatal("response delivered after cancellation")
		}
	})
}
