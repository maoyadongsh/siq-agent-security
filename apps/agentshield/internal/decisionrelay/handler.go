package decisionrelay

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"regexp"
	"strings"
	"time"
)

var (
	bearerPattern        = regexp.MustCompile(`^ri-[a-f0-9]{32}\.[a-f0-9]{64}$`)
	sessionSuffixPattern = regexp.MustCompile(`^[a-f0-9]{64}$`)
)

type Relay struct {
	config Config
	client *http.Client
	routes map[string]bool
}

func New(cfg Config) (*Relay, error) {
	if err := cfg.Validate(); err != nil {
		return nil, errors.New("decision relay: invalid configuration")
	}
	transport := &http.Transport{
		Proxy:               nil,
		DialContext:         (&net.Dialer{Timeout: cfg.UpstreamTimeout()}).DialContext,
		DisableCompression:  true,
		ForceAttemptHTTP2:   false,
		MaxIdleConns:        4,
		MaxIdleConnsPerHost: 2,
		IdleConnTimeout:     30 * time.Second,
	}
	return NewWithClient(cfg, &http.Client{
		Transport: transport,
		Timeout:   cfg.UpstreamTimeout(),
		CheckRedirect: func(_ *http.Request, _ []*http.Request) error {
			return http.ErrUseLastResponse
		},
	})
}

func NewWithClient(cfg Config, client *http.Client) (*Relay, error) {
	if err := cfg.Validate(); err != nil || client == nil {
		return nil, errors.New("decision relay: invalid configuration")
	}
	routes := make(map[string]bool, len(AllowedRoutes))
	for _, route := range AllowedRoutes {
		routes[route] = true
	}
	return &Relay{config: cfg, client: client, routes: routes}, nil
}

func writeError(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": code})
}

func (relay *Relay) ServeHTTP(w http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "relay_post_required")
		return
	}
	if request.URL.RawQuery != "" || request.URL.Fragment != "" || !relay.routes[request.URL.Path] {
		writeError(w, http.StatusNotFound, "relay_route_not_allowed")
		return
	}
	authorizations := request.Header.Values("Authorization")
	if len(authorizations) != 1 || !strings.HasPrefix(authorizations[0], "Bearer ") {
		writeError(w, http.StatusUnauthorized, "relay_runtime_identity_required")
		return
	}
	credential := strings.TrimPrefix(authorizations[0], "Bearer ")
	if !bearerPattern.MatchString(credential) ||
		!strings.HasPrefix(credential, relay.config.Binding.RuntimeIdentityID+".") {
		writeError(w, http.StatusUnauthorized, "relay_runtime_identity_required")
		return
	}
	body, err := io.ReadAll(http.MaxBytesReader(w, request.Body, relay.config.MaxRequestBytes))
	if err != nil || !relay.validBody(request.URL.Path, body) {
		writeError(w, http.StatusBadRequest, "relay_binding_mismatch")
		return
	}

	ctx, cancel := context.WithTimeout(request.Context(), relay.config.UpstreamTimeout())
	defer cancel()
	upstream, err := http.NewRequestWithContext(
		ctx, http.MethodPost, relay.config.Upstream+request.URL.Path, bytes.NewReader(body),
	)
	if err != nil {
		writeError(w, http.StatusBadGateway, "relay_upstream_unavailable")
		return
	}
	upstream.Header.Set("Authorization", "Bearer "+credential)
	upstream.Header.Set("Content-Type", "application/json")
	upstream.Header.Set("Accept", "application/json")
	response, err := relay.client.Do(upstream)
	if err != nil {
		writeError(w, http.StatusBadGateway, "relay_upstream_unavailable")
		return
	}
	defer response.Body.Close()
	if response.StatusCode >= 300 && response.StatusCode < 400 {
		writeError(w, http.StatusBadGateway, "relay_upstream_redirect_refused")
		return
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, relay.config.MaxResponseBytes+1))
	if err != nil || int64(len(raw)) > relay.config.MaxResponseBytes {
		writeError(w, http.StatusBadGateway, "relay_upstream_response_invalid")
		return
	}
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(response.StatusCode)
	_, _ = w.Write(raw)
}

func (relay *Relay) validBody(path string, raw []byte) bool {
	if len(raw) == 0 || int64(len(raw)) > relay.config.MaxRequestBytes || !uniqueJSON(raw) {
		return false
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	token, err := decoder.Token()
	if err != nil || token != json.Delim('{') {
		return false
	}
	values := map[string]string{}
	identityNames := map[string]string{"platform": "", "agent_id": "", "session_id": ""}
	for decoder.More() {
		keyToken, err := decoder.Token()
		name, ok := keyToken.(string)
		if err != nil || !ok {
			return false
		}
		var value json.RawMessage
		if decoder.Decode(&value) != nil {
			return false
		}
		for canonical := range identityNames {
			if strings.EqualFold(name, canonical) {
				if name != canonical || identityNames[canonical] != "" {
					return false
				}
				var text string
				if json.Unmarshal(value, &text) != nil || text == "" {
					return false
				}
				identityNames[canonical] = text
				values[canonical] = text
			}
		}
	}
	if end, err := decoder.Token(); err != nil || end != json.Delim('}') {
		return false
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || !relay.validSession(values["session_id"]) {
		return false
	}
	if path == "/v1/runtime-sessions" {
		return values["platform"] == "" && values["agent_id"] == ""
	}
	return values["platform"] == relay.config.Binding.Platform &&
		values["agent_id"] == relay.config.Binding.AgentID
}

func (relay *Relay) validSession(session string) bool {
	prefix := relay.config.Binding.SessionNamespace + ":"
	return strings.HasPrefix(session, prefix) &&
		sessionSuffixPattern.MatchString(strings.TrimPrefix(session, prefix))
}
