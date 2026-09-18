package skillimport

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"net"
	"net/netip"
	"os"
	"testing"
	"time"
)

// This preflight is a diagnostic harness, not an acceptance test. It is
// skipped unless SIQ_LIVE_HOSTED_PREFLIGHT=1 and it never asserts an outcome:
// it reports what the *production* transport (ADR-035/ADR-0051) observes when
// it is pointed at the real hosted endpoints. It performs no process
// execution, reads no environment configuration, honours no proxy variable,
// and cannot relax DNS, TLS, redirect or private-address policy - the
// production seams are the same ones fetchHostedGit uses.
//
// Production remains closed by productionGitFetch; running this file never
// opens the git gate.

const preflightGate = "SIQ_LIVE_HOSTED_PREFLIGHT"

var preflightHosts = []string{"github.com", "api.github.com", "codeload.github.com"}

func preflightEmit(t *testing.T, leg string, fields map[string]any) {
	t.Helper()
	fields["leg"] = leg
	raw, err := json.Marshal(fields)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	t.Logf("SIQ_PREFLIGHT %s", raw)
}

func preflightErrorClass(err error) string {
	switch {
	case err == nil:
		return "ok"
	case errors.Is(err, ErrURLBlocked):
		return "url_blocked"
	case errors.Is(err, ErrLimit):
		return "limit"
	case errors.Is(err, ErrSourceUnavailable):
		return "source_unavailable"
	case errors.Is(err, ErrDownloadFailed):
		return "download_failed"
	case errors.Is(err, context.DeadlineExceeded):
		return "deadline"
	default:
		return "other:" + err.Error()
	}
}

func TestLiveHostedSourcePreflight(t *testing.T) {
	if os.Getenv(preflightGate) != "1" {
		t.Skipf("set %s=1 to run the live hosted-source preflight", preflightGate)
	}
	resolver := &net.Resolver{PreferGo: true, StrictErrors: true}

	for _, host := range preflightHosts {
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		ips, err := resolver.LookupNetIP(ctx, "ip", host)
		cancel()
		var strings []string
		var public []bool
		for _, ip := range ips {
			strings = append(strings, ip.String())
			public = append(public, publicAddress(ip))
		}
		if strings == nil {
			strings = []string{}
		}
		if public == nil {
			public = []bool{}
		}
		preflightEmit(t, "dns", map[string]any{
			"host": host, "addresses": strings, "public_address": public,
			"error": errString(err),
		})
	}

	// Plain TCP reachability of a fixed public address, with no resolver and
	// no proxy involved: distinguishes "no direct egress" from "hostname
	// resolves to a non-public address".
	dialer := &net.Dialer{Timeout: 3 * time.Second}
	for _, target := range []string{"1.1.1.1:443", "8.8.8.8:443"} {
		conn, err := dialer.DialContext(context.Background(), "tcp", target)
		ok := err == nil
		if ok {
			conn.Close()
		}
		preflightEmit(t, "direct_tcp", map[string]any{"target": target, "connected": ok, "error": errString(err)})
	}

	// Second opinion on resolution, independent of the system resolver: a
	// read-only UDP query to a fixed public resolver. This changes no system
	// DNS configuration; it distinguishes "the host has no egress" from
	// "the system resolver answers with a non-public address".
	external := &net.Resolver{PreferGo: true, StrictErrors: true, Dial: func(ctx context.Context, network, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: 3 * time.Second}).DialContext(ctx, "udp", "1.1.1.1:53")
	}}
	for _, host := range preflightHosts {
		ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
		ips, err := external.LookupNetIP(ctx, "ip", host)
		cancel()
		var strings []string
		for _, ip := range ips {
			strings = append(strings, ip.String())
		}
		if strings == nil {
			strings = []string{}
		}
		preflightEmit(t, "dns_external_1.1.1.1", map[string]any{"host": host, "addresses": strings, "error": errString(err)})
	}

	endpoints := []struct {
		leg      string
		source   string
		opts     fetchOptions
		display  string
		isGitURL bool
	}{
		{
			leg: "github_locator", source: "https://github.com/octocat/Hello-World",
			display: "https://github.com/octocat/Hello-World", isGitURL: true,
		},
		{
			leg: "api_commit", source: "https://api.github.com/repos/octocat/Hello-World/commits/HEAD",
			display: "https://api.github.com/repos/octocat/Hello-World/commits/HEAD",
			opts:    fetchOptions{accept: "application/json", maxRedirects: 0, maxBytes: 1 << 20, status: hostedStatusError},
		},
		{
			leg: "codeload_archive", source: "https://codeload.github.com/octocat/Hello-World/zip/7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
			display: "https://codeload.github.com/octocat/Hello-World/zip/7fd1a60b01f91b314f59955a4e4d4e80d8edf11d",
			opts:    fetchOptions{accept: "application/zip", maxRedirects: 0, maxBytes: maxArchiveBytes, status: hostedStatusError},
		},
	}

	f := httpsFetcher()
	for _, ep := range endpoints {
		record := map[string]any{"source": ep.display}
		if _, err := downloadURL(ep.source); err != nil {
			record["locator_policy"] = "rejected:" + preflightErrorClass(err)
		} else {
			record["locator_policy"] = "accepted"
		}
		if ep.isGitURL {
			repo, err := parseHostedRepo(ep.source)
			record["repo_parse"] = errString(err)
			record["owner"] = repo.owner
			record["repo"] = repo.repo
		}
		if record["locator_policy"] == "accepted" {
			ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
			started := time.Now()
			got, err := f.fetchWith(ctx, ep.source, ep.opts)
			elapsed := time.Since(started)
			cancel()
			record["error"] = errString(err)
			record["error_class"] = preflightErrorClass(err)
			record["elapsed_ms"] = elapsed.Milliseconds()
			record["bytes"] = len(got.raw)
			record["final_url"] = got.finalURL
		}
		preflightEmit(t, ep.leg, record)
	}

	// TLS policy observation against a resolved address only when the
	// production policy would dial it; the preflight never contacts an
	// address the production transport rejects.
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	systemIPs, _ := resolver.LookupNetIP(ctx, "ip", "api.github.com")
	cancel()
	ctx, cancel = context.WithTimeout(context.Background(), 6*time.Second)
	externalIPs, _ := external.LookupNetIP(ctx, "ip", "api.github.com")
	cancel()
	for _, source := range []struct {
		name string
		ips  []netip.Addr
	}{{"system_resolver", systemIPs}, {"external_resolver", externalIPs}} {
		for _, ip := range source.ips {
			if !publicAddress(ip) {
				preflightEmit(t, "tls", map[string]any{"resolution": source.name, "address": ip.String(), "attempted": false, "reason": "non_public_address_policy"})
				continue
			}
			d := &net.Dialer{Timeout: 3 * time.Second}
			conn, err := tls.DialWithDialer(d, "tcp", net.JoinHostPort(ip.Unmap().String(), "443"), &tls.Config{
				MinVersion: tls.VersionTLS12, ServerName: "api.github.com",
			})
			rec := map[string]any{"resolution": source.name, "address": ip.String(), "attempted": true, "error": errString(err)}
			if err == nil {
				state := conn.ConnectionState()
				rec["tls_version"] = tls.VersionName(state.Version)
				rec["cipher"] = tls.CipherSuiteName(state.CipherSuite)
				rec["server_name"] = state.ServerName
				rec["verified_chains"] = len(state.VerifiedChains)
				rec["peer_subject"] = state.PeerCertificates[0].Subject.String()
				rec["not_after"] = state.PeerCertificates[0].NotAfter.UTC().Format(time.RFC3339)
				conn.Close()
			}
			preflightEmit(t, "tls", rec)
		}
	}

	// The production gate itself, on the real locator.
	dst := t.TempDir() + "/hosted-preflight-dst"
	_, gateErr := productionGitFetch(context.Background(), "https://github.com/octocat/Hello-World", "main", dst)
	preflightEmit(t, "production_gate", map[string]any{
		"error": errString(gateErr), "unavailable": errors.Is(gateErr, ErrGitTransportUnavailable),
		"destination_created": preflightExists(dst),
	})
	if _, err := fetchHostedGit(context.Background(), "https://github.com/octocat/Hello-World", "main", dst); err != nil {
		preflightEmit(t, "fetch_hosted_git", map[string]any{"error": errString(err), "error_class": preflightErrorClass(err)})
	}
}

func errString(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func preflightExists(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}
