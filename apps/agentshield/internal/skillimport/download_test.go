package skillimport

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/netip"
	"strconv"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Only the test dialer maps validated public IPs to a local TLS server.
// Production still performs ordinary certificate and hostname verification.
func tlsFetcher(t *testing.T, handler http.HandlerFunc) archiveFetcher {
	t.Helper()
	pub, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	cert := &x509.Certificate{SerialNumber: big.NewInt(1), DNSNames: []string{"download.example.com", "cdn.example.com"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, cert, cert, pub, key)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	roots := x509.NewCertPool()
	roots.AddCert(parsed)
	server := httptest.NewUnstartedServer(handler)
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.TLS = &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}, MinVersion: tls.VersionTLS12}
	server.StartTLS()
	t.Cleanup(server.Close)
	return archiveFetcher{roots: roots, lookup: func(ctx context.Context, network, host string) ([]netip.Addr, error) {
		if network != "ip" {
			t.Errorf("unexpected DNS network: %s", network)
		}
		return []netip.Addr{netip.MustParseAddr("93.184.216.34")}, nil
	}, dial: func(ctx context.Context, network, address string) (net.Conn, error) {
		if network != "tcp" || address != "93.184.216.34:443" {
			t.Errorf("unvalidated dial: %s %s", network, address)
			return nil, ErrURLBlocked
		}
		return (&net.Dialer{}).DialContext(ctx, network, server.Listener.Addr().String())
	}}
}

func TestDownloadURLPolicy(t *testing.T) {
	for _, raw := range []string{"", "http://download.example.com/a", "https://localhost/a", "https://x.local/a", "https://x.test/a", "https://x.invalid/a", "https://x.onion/a", "https://x.localhost/a", "https://download.example.com./a", "https://user:secret@download.example.com/a", "https://download.example.com:444/a", "https://download.example.com:/a", "https://download.example.com/a#", "https://download.example.com/a#fragment", "https://download.example.com/a\\b", "https://download.example.com/a\nb", "https://下载.example.com/a", "https://-a.example.com/a", "https://a..example.com/a", "https://[fe80::1%25eth0]/a", "https://127.0.0.1/a", "https://[::ffff:127.0.0.1]/a", "https://download.example.com/" + strings.Repeat("x", 4096), "https://download.example.com/\xff"} {
		if _, err := downloadURL(raw); !errors.Is(err, ErrURLBlocked) {
			t.Errorf("accepted unsafe URL %q: %v", raw, err)
		}
	}
	for _, raw := range []string{"https://DOWNLOAD.example.com:443", "https://93.184.216.34/a", "https://[2606:4700:4700::1111]/a", "https://download.example.com/a?token=opaque%2Bvalue"} {
		if _, err := downloadURL(raw); err != nil {
			t.Errorf("rejected valid URL %q: %v", raw, err)
		}
	}
	u, err := downloadURL("https://DOWNLOAD.example.com:443")
	if err != nil || u.String() != "https://download.example.com/" {
		t.Fatal(u, err)
	}
	for _, value := range []string{"0.0.0.0", "10.1.1.1", "100.64.0.1", "127.0.0.2", "169.254.169.254", "172.16.0.1", "192.0.0.9", "192.0.2.1", "192.31.196.1", "192.52.193.1", "192.88.99.1", "192.168.1.1", "192.175.48.1", "198.18.0.1", "198.51.100.1", "203.0.113.1", "224.0.0.1", "255.255.255.255", "::1", "::ffff:10.0.0.1", "64:ff9b::5db8:d822", "100::1", "2001::1", "2001:20::1", "2001:db8::1", "2002:5db8:d822::1", "2620:4f:8000::1", "3fff::1", "fc00::1", "fe80::1"} {
		if publicAddress(netip.MustParseAddr(value)) {
			t.Errorf("special address allowed: %s", value)
		}
	}
	for _, value := range []string{"93.184.216.34", "8.8.8.8", "::ffff:8.8.8.8", "2606:4700:4700::1111"} {
		if !publicAddress(netip.MustParseAddr(value)) {
			t.Errorf("public address blocked: %s", value)
		}
	}
}

func TestDownloadTLSRedirectAndHeaders(t *testing.T) {
	t.Setenv("HTTPS_PROXY", "http://127.0.0.1:1")
	t.Setenv("ALL_PROXY", "http://127.0.0.1:1")
	var calls atomic.Int32
	f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		if r.Method != "GET" || r.Header.Get("User-Agent") != "SIQ-Skill-Importer/1" || r.Header.Get("Accept-Encoding") != "identity" || r.Header.Get("Referer") != "" || r.Header.Get("Authorization") != "" || r.Header.Get("Cookie") != "" {
			t.Errorf("unexpected request headers: %v", r.Header)
		}
		if r.URL.Path == "/start" {
			w.Header().Set("Set-Cookie", "private=value")
			http.Redirect(w, r, "https://cdn.example.com/end", 302)
			return
		}
		if r.Host != "cdn.example.com" {
			t.Errorf("TLS host lost: %s", r.Host)
		}
		_, _ = w.Write([]byte("zip bytes"))
	})
	got, err := f.fetch(context.Background(), "https://download.example.com/start?token=private")
	if err != nil || string(got.raw) != "zip bytes" || got.finalURL != "https://cdn.example.com/end" || calls.Load() != 2 {
		t.Fatal(got, err, calls.Load())
	}
	for _, host := range []string{"wrong.example.com", "download.example.com"} {
		bad := f
		if host == "download.example.com" {
			bad.roots = x509.NewCertPool()
		}
		_, err := bad.fetch(context.Background(), "https://"+host+"/?token=private")
		if !errors.Is(err, ErrDownloadFailed) || strings.Contains(err.Error(), "private") {
			t.Fatal("TLS failure not sanitized", err)
		}
	}
	if calls.Load() != 2 {
		t.Fatal("invalid TLS reached handler")
	}
}

func TestDownloadRedirectBoundaries(t *testing.T) {
	for _, count := range []int{3, 4} {
		t.Run(fmt.Sprint(count), func(t *testing.T) {
			var calls atomic.Int32
			f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				n, _ := strconv.Atoi(strings.TrimPrefix(r.URL.Path, "/"))
				if n < count {
					http.Redirect(w, r, fmt.Sprintf("/%d", n+1), 302)
					return
				}
				_, _ = w.Write([]byte("ok"))
			})
			_, err := f.fetch(context.Background(), "https://download.example.com/0")
			if count == 3 && err != nil {
				t.Fatal(err)
			}
			if count == 4 && !errors.Is(err, ErrURLBlocked) {
				t.Fatal("redirect limit missed", err)
			}
			if calls.Load() != 4 {
				t.Fatal("unexpected number of requests", calls.Load())
			}
		})
	}
	for _, location := range []string{"http://download.example.com/end", "https://127.0.0.1/end", "https://user:secret@cdn.example.com/end", "https://cdn.example.com:8443/end"} {
		t.Run(location, func(t *testing.T) {
			var calls atomic.Int32
			f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) { calls.Add(1); http.Redirect(w, r, location, 302) })
			_, err := f.fetch(context.Background(), "https://download.example.com/start")
			if !errors.Is(err, ErrURLBlocked) || calls.Load() != 1 {
				t.Fatal("unsafe redirect contacted", calls.Load(), err)
			}
		})
	}
	// The same hostname resolving differently after a redirect must be checked again.
	var lookups atomic.Int32
	f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, "/again", 302) })
	f.lookup = func(context.Context, string, string) ([]netip.Addr, error) {
		if lookups.Add(1) == 1 {
			return []netip.Addr{netip.MustParseAddr("93.184.216.34")}, nil
		}
		return []netip.Addr{netip.MustParseAddr("127.0.0.1")}, nil
	}
	if _, err := f.fetch(context.Background(), "https://download.example.com/start"); !errors.Is(err, ErrURLBlocked) || lookups.Load() != 2 {
		t.Fatal("DNS rebinding allowed", err, lookups.Load())
	}
}

func TestDownloadDNSLimitsAndCancellation(t *testing.T) {
	for _, count := range []int{2, 32, 33} {
		var attempts int
		ips := make([]netip.Addr, count)
		for i := range ips {
			ips[i] = netip.MustParseAddr("93.184.216.34")
		}
		if count == 2 {
			ips[1] = netip.MustParseAddr("10.0.0.1")
		}
		f := archiveFetcher{lookup: func(context.Context, string, string) ([]netip.Addr, error) { return ips, nil }, dial: func(context.Context, string, string) (net.Conn, error) {
			attempts++
			return nil, errors.New("dial failed")
		}}
		_, err := f.connect(context.Background(), "tcp", "download.example.com:443")
		want := ErrDownloadFailed
		wantAttempts := 8
		if count == 2 {
			want = ErrURLBlocked
			wantAttempts = 0
		}
		if count == 33 {
			want = ErrLimit
			wantAttempts = 0
		}
		if !errors.Is(err, want) || attempts != wantAttempts {
			t.Fatal(count, attempts, err)
		}
	}
	started, finished := make(chan struct{}), make(chan struct{})
	f := archiveFetcher{lookup: func(ctx context.Context, _, _ string) ([]netip.Addr, error) {
		close(started)
		<-ctx.Done()
		close(finished)
		return nil, ctx.Err()
	}, dial: func(context.Context, string, string) (net.Conn, error) {
		t.Error("dial after canceled DNS")
		return nil, ErrDownloadFailed
	}}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	result := make(chan error, 1)
	go func() { _, err := f.fetch(ctx, "https://download.example.com/a"); result <- err }()
	select {
	case <-started:
	case <-time.After(3 * time.Second):
		t.Fatal("DNS did not start")
	}
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("fetch did not cancel")
	}
	select {
	case <-finished:
	case <-time.After(3 * time.Second):
		t.Fatal("DNS outlived canceled download")
	}
}

func TestDownloadResponseBounds(t *testing.T) {
	for _, mode := range []string{"status", "encoded", "empty", "short", "declared_over", "chunked_over", "exact"} {
		t.Run(mode, func(t *testing.T) {
			f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) {
				switch mode {
				case "status":
					w.WriteHeader(403)
					_, _ = w.Write([]byte("private upstream diagnostic"))
				case "encoded":
					w.Header().Set("Content-Encoding", "gzip")
					_, _ = w.Write([]byte("opaque"))
				case "empty":
					w.WriteHeader(200)
				case "short":
					w.Header().Set("Content-Length", "20")
					_, _ = w.Write([]byte("short"))
				case "declared_over":
					w.Header().Set("Content-Length", fmt.Sprint(maxArchiveBytes+1))
					w.WriteHeader(200)
				case "chunked_over", "exact":
					count := maxArchiveBytes
					if mode == "chunked_over" {
						count++
						w.(http.Flusher).Flush()
					} else {
						w.Header().Set("Content-Length", fmt.Sprint(count))
					}
					chunk := bytes.Repeat([]byte("x"), 64<<10)
					for count > 0 {
						n := int64(len(chunk))
						if n > count {
							n = count
						}
						if _, err := w.Write(chunk[:n]); err != nil {
							return
						}
						count -= n
					}
				}
			})
			got, err := f.fetch(context.Background(), "https://download.example.com/a?token=private")
			want := ErrDownloadFailed
			if mode == "declared_over" || mode == "chunked_over" {
				want = ErrLimit
			}
			if mode == "exact" {
				if err != nil || int64(len(got.raw)) != maxArchiveBytes {
					t.Fatal(len(got.raw), err)
				}
				return
			}
			if !errors.Is(err, want) || len(got.raw) != 0 {
				t.Fatal("response boundary", len(got.raw), err)
			}
		})
	}
}

func TestDownloadCancellationDuringResponse(t *testing.T) {
	for _, phase := range []string{"headers", "body"} {
		t.Run(phase, func(t *testing.T) {
			reached := make(chan struct{})
			f := tlsFetcher(t, func(w http.ResponseWriter, r *http.Request) {
				if phase == "body" {
					_, _ = w.Write([]byte("partial"))
					w.(http.Flusher).Flush()
				}
				close(reached)
				<-r.Context().Done()
			})
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			done := make(chan error, 1)
			go func() { _, err := f.fetch(ctx, "https://download.example.com/slow"); done <- err }()
			select {
			case <-reached:
			case <-time.After(3 * time.Second):
				t.Fatal("request never reached TLS handler")
			}
			cancel()
			select {
			case err := <-done:
				if !errors.Is(err, context.Canceled) {
					t.Fatal("partial result survived cancellation", err)
				}
			case <-time.After(3 * time.Second):
				t.Fatal("response did not cancel")
			}
		})
	}
}
