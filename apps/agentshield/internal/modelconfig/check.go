package modelconfig

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Result struct {
	Schema      string `json:"schema_version"`
	ID          string `json:"id"`
	Fingerprint string `json:"fingerprint"`
	Status      string `json:"status"`
	ObservedAt  string `json:"observed_at"`
	ExpiresAt   string `json:"expires_at"`
	Inference   bool   `json:"inference_verified"`
}

func allowedIP(ip net.IP) bool {
	return ip != nil && !ip.IsUnspecified() && !ip.IsMulticast() && !ip.IsLinkLocalUnicast() && !ip.IsLinkLocalMulticast() && !ip.Equal(net.ParseIP("100.100.100.200")) && !ip.Equal(net.ParseIP("168.63.129.16")) && !ip.Equal(net.ParseIP("fd00:ec2::254"))
}
func endpoint(raw string) (*url.URL, error) {
	u, err := url.Parse(raw)
	if err != nil || len(raw) > 2048 || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Opaque != "" || strings.ContainsAny(raw, "\r\n\\") {
		return nil, invalid
	}
	ip := net.ParseIP(u.Hostname())
	if ip != nil && !allowedIP(ip) {
		return nil, invalid
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && (u.Hostname() == "localhost" || ip != nil && (ip.IsLoopback() || ip.IsPrivate()))) {
		return nil, invalid
	}
	if len(u.Scheme+"://"+u.Host) > 512 {
		return nil, invalid
	}
	return u, nil
}

// Check requests only the explicit service's model listing. No redirects,
// proxy environment, prompts, generated tokens or automatic fallback.
func Check(ctx context.Context, t Target) Result {
	now := time.Now().UTC()
	r := Result{Schema: "local-model-connection-result/v1", ID: t.Item.ID, Fingerprint: t.Item.Fingerprint, Status: "unreachable", ObservedAt: now.Format(time.RFC3339Nano), ExpiresAt: now.Add(30 * time.Second).Format(time.RFC3339Nano)}
	u, err := endpoint(t.URL)
	if err != nil || !t.Item.CanCheck {
		return r
	}
	u.Path = strings.TrimRight(u.Path, "/") + "/models"
	if u.RawPath != "" {
		u.RawPath = strings.TrimRight(u.RawPath, "/") + "/models"
	}
	ctx, cancel := context.WithTimeout(ctx, 6*time.Second)
	defer cancel()
	transport := modelTransport(u)
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return r
	}
	req.Header.Set("Accept", "application/json")
	if t.Key != "" {
		req.Header.Set("Authorization", "Bearer "+t.Key)
	}
	response, err := client.Do(req)
	if err != nil {
		return r
	}
	defer response.Body.Close()
	switch {
	case response.StatusCode == 401 || response.StatusCode == 403:
		r.Status = "auth_failed"
		return r
	case response.StatusCode == 429:
		r.Status = "rate_limited"
		return r
	case response.StatusCode == 404 || response.StatusCode == 405 || response.StatusCode >= 300 && response.StatusCode < 400:
		r.Status = "unsupported_response"
		return r
	case response.StatusCode != 200:
		r.Status = "service_error"
		return r
	}
	r.Status = "unsupported_response"
	if !strings.HasPrefix(strings.ToLower(response.Header.Get("Content-Type")), "application/json") {
		return r
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, (1<<20)+1))
	if err != nil || len(raw) > 1<<20 || !uniqueJSON(raw) {
		return r
	}
	var body struct {
		Data []struct {
			ID string `json:"id"`
		} `json:"data"`
	}
	if json.Unmarshal(raw, &body) != nil || body.Data == nil || len(body.Data) > 10000 {
		return r
	}
	seen := map[string]bool{}
	matched := false
	for _, model := range body.Data {
		if model.ID == "" || len(model.ID) > 1024 || seen[model.ID] {
			return r
		}
		seen[model.ID] = true
		if model.ID == t.Item.Model {
			matched = true
		}
	}
	r.Status = "not_listed"
	if matched {
		r.Status = "listed"
	}
	return r
}

func modelTransport(u *url.URL) *http.Transport {
	return &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}, DisableKeepAlives: true,
		DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
			host, port, e := net.SplitHostPort(address)
			if e != nil {
				return nil, invalid
			}
			ips, e := net.DefaultResolver.LookupIPAddr(ctx, host)
			if e != nil || len(ips) == 0 {
				return nil, invalid
			}
			for _, ip := range ips {
				if !allowedIP(ip.IP) || u.Scheme == "http" && !ip.IP.IsLoopback() && !ip.IP.IsPrivate() {
					return nil, invalid
				}
			}
			var dialer net.Dialer
			return dialer.DialContext(ctx, network, net.JoinHostPort(ips[0].IP.String(), port))
		}}
}
