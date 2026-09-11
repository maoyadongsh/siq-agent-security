package skillimport

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"io"
	"net"
	"net/http"
	"net/netip"
	"net/url"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

var ErrURLBlocked = errors.New("skill_import_url_blocked")
var ErrDownloadFailed = errors.New("skill_import_download_failed")
var ErrArchiveMismatch = errors.New("skill_import_archive_mismatch")

// Conservative special-use exclusions, reviewed against IANA in ADR-035.
var excludedIPv4 = prefixes("0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24", "192.31.196.0/24", "192.52.193.0/24", "192.88.99.0/24", "192.168.0.0/16", "192.175.48.0/24", "198.18.0.0/15", "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4")
var excludedIPv6 = prefixes("2001::/23", "2001:db8::/32", "2002::/16", "2620:4f:8000::/48", "3fff::/20")
var globalIPv6 = netip.MustParsePrefix("2000::/3")

func prefixes(values ...string) []netip.Prefix {
	result := make([]netip.Prefix, 0, len(values))
	for _, v := range values {
		result = append(result, netip.MustParsePrefix(v))
	}
	return result
}
func publicAddress(ip netip.Addr) bool {
	if !ip.IsValid() || ip.Zone() != "" {
		return false
	}
	ip = ip.Unmap()
	if !ip.IsGlobalUnicast() || ip.IsPrivate() {
		return false
	}
	excluded := excludedIPv4
	if ip.Is6() {
		if !globalIPv6.Contains(ip) {
			return false
		}
		excluded = excludedIPv6
	}
	for _, block := range excluded {
		if block.Contains(ip) {
			return false
		}
	}
	return true
}
func downloadURL(raw string) (*url.URL, error) {
	if len(raw) == 0 || len(raw) > 4096 || !utf8.ValidString(raw) || strings.Contains(raw, "#") || strings.IndexFunc(raw, func(r rune) bool { return unicode.IsSpace(r) || unicode.IsControl(r) }) >= 0 || strings.Contains(raw, "\\") {
		return nil, ErrURLBlocked
	}
	u, err := url.Parse(raw)
	if err != nil || u.Scheme != "https" || u.Opaque != "" || u.User != nil || u.Fragment != "" || u.RawFragment != "" || u.Host == "" || strings.HasSuffix(u.Host, ":") || (u.Port() != "" && u.Port() != "443") {
		return nil, ErrURLBlocked
	}
	host := strings.ToLower(u.Hostname())
	if ip, err := netip.ParseAddr(host); err == nil {
		if !publicAddress(ip) {
			return nil, ErrURLBlocked
		}
		host = ip.String()
		if ip.Is6() {
			host = "[" + host + "]"
		}
	} else {
		if len(host) > 253 || !strings.Contains(host, ".") || strings.HasSuffix(host, ".") {
			return nil, ErrURLBlocked
		}
		for _, suffix := range []string{".localhost", ".local", ".invalid", ".test", ".onion"} {
			if strings.HasSuffix(host, suffix) {
				return nil, ErrURLBlocked
			}
		}
		for _, label := range strings.Split(host, ".") {
			if len(label) == 0 || len(label) > 63 || label[0] == '-' || label[len(label)-1] == '-' {
				return nil, ErrURLBlocked
			}
			for _, c := range label {
				if !(c >= 'a' && c <= 'z') && !(c >= '0' && c <= '9') && c != '-' {
					return nil, ErrURLBlocked
				}
			}
		}
	}
	u.Host = host // Explicit :443 is equivalent; TLS still authenticates this host.
	if u.Path == "" {
		u.Path = "/"
	}
	return u, nil
}

type downloadedArchive struct {
	raw      []byte
	finalURL string
}

// Test seams are private: no environment flag can relax DNS or TLS policy.
type archiveFetcher struct {
	lookup func(context.Context, string, string) ([]netip.Addr, error)
	dial   func(context.Context, string, string) (net.Conn, error)
	roots  *x509.CertPool
}

func fetchHTTPS(ctx context.Context, source string) (downloadedArchive, error) {
	resolver := &net.Resolver{PreferGo: true, StrictErrors: true}
	dialer := &net.Dialer{Timeout: 3 * time.Second}
	f := archiveFetcher{lookup: resolver.LookupNetIP, dial: dialer.DialContext}
	return f.fetch(ctx, source)
}
func (f archiveFetcher) connect(ctx context.Context, network, address string) (net.Conn, error) {
	host, port, err := net.SplitHostPort(address)
	if err != nil || port != "443" || network != "tcp" {
		return nil, ErrURLBlocked
	}
	var ips []netip.Addr
	if ip, e := netip.ParseAddr(host); e == nil {
		ips = []netip.Addr{ip}
	} else {
		ips, err = f.lookup(ctx, "ip", host)
	}
	if err != nil || len(ips) == 0 {
		return nil, ErrDownloadFailed
	}
	if len(ips) > 32 {
		return nil, ErrLimit
	}
	for _, ip := range ips {
		if !publicAddress(ip) {
			return nil, ErrURLBlocked
		}
	}
	for i, ip := range ips {
		if i >= 8 {
			break
		}
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		conn, err := f.dial(ctx, "tcp", net.JoinHostPort(ip.Unmap().String(), "443"))
		if err == nil {
			return conn, nil
		}
	}
	return nil, ErrDownloadFailed
}
func downloadHeaders(r *http.Request) {
	r.Header = make(http.Header)
	r.Header.Set("User-Agent", "SIQ-Skill-Importer/1")
	r.Header.Set("Accept", "application/zip, application/octet-stream")
	r.Header.Set("Accept-Encoding", "identity")
	r.Host = ""
}
func (f archiveFetcher) fetch(ctx context.Context, source string) (downloadedArchive, error) {
	var none downloadedArchive
	if ctx == nil {
		ctx = context.Background()
	}
	ctx, cancel := context.WithTimeout(ctx, 45*time.Second)
	defer cancel()
	parsed, err := downloadURL(source)
	if err != nil {
		return none, err
	}
	transport := &http.Transport{Proxy: nil, DialContext: func(_ context.Context, network, address string) (net.Conn, error) {
		return f.connect(ctx, network, address)
	}, DisableKeepAlives: true, DisableCompression: true,
		TLSHandshakeTimeout: 10 * time.Second, ResponseHeaderTimeout: 10 * time.Second, MaxResponseHeaderBytes: 32 << 10,
		MaxConnsPerHost: 1, TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: f.roots},
		TLSNextProto: map[string]func(string, *tls.Conn) http.RoundTripper{}}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) > 3 {
			return ErrURLBlocked
		}
		parsed, err := downloadURL(req.URL.String())
		if err != nil {
			return err
		}
		req.URL = parsed
		downloadHeaders(req)
		return nil
	}}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, parsed.String(), nil)
	if err != nil {
		return none, ErrURLBlocked
	}
	downloadHeaders(req)
	resp, err := client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return none, ctx.Err()
		}
		if errors.Is(err, ErrURLBlocked) {
			return none, ErrURLBlocked
		}
		if errors.Is(err, ErrLimit) {
			return none, ErrLimit
		}
		return none, ErrDownloadFailed
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return none, ErrDownloadFailed
	}
	encoding := strings.TrimSpace(resp.Header.Get("Content-Encoding"))
	if encoding != "" && !strings.EqualFold(encoding, "identity") {
		return none, ErrDownloadFailed
	}
	if resp.ContentLength > maxArchiveBytes {
		return none, ErrLimit
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, maxArchiveBytes+1))
	if ctx.Err() != nil {
		return none, ctx.Err()
	}
	if int64(len(raw)) > maxArchiveBytes {
		return none, ErrLimit
	}
	if err != nil || len(raw) == 0 || (resp.ContentLength >= 0 && resp.ContentLength != int64(len(raw))) {
		return none, ErrDownloadFailed
	}
	return downloadedArchive{raw: raw, finalURL: resp.Request.URL.String()}, nil
}
