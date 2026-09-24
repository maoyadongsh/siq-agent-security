package openshell

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"sort"
	"strings"
	"time"
)

type RegisteredGateway struct {
	ID          string `json:"gateway_id"`
	Name        string `json:"name"`
	Endpoint    string `json:"endpoint_display"`
	Active      bool   `json:"native_active"`
	Fingerprint string `json:"configuration_fingerprint"`
}

type GatewayCatalog struct {
	Schema           string              `json:"schema_version"`
	ObservedAt       string              `json:"observed_at"`
	State            string              `json:"state"`
	Items            []RegisteredGateway `json:"items"`
	Started          bool                `json:"started_gateway"`
	ChangedSelection bool                `json:"changed_native_selection"`
}

type GatewayTargets struct {
	Schema      string        `json:"schema_version"`
	ID          string        `json:"gateway_id"`
	Fingerprint string        `json:"configuration_fingerprint"`
	Catalog     TargetCatalog `json:"catalog"`
}

type GatewayInspection struct {
	Schema      string           `json:"schema_version"`
	ID          string           `json:"gateway_id"`
	Fingerprint string           `json:"configuration_fingerprint"`
	Inspection  TargetInspection `json:"inspection"`
}

// Native CLI output is untrusted. Reject duplicate keys at every nesting level.
func uniqueGatewayJSON(raw []byte) bool {
	d := json.NewDecoder(bytes.NewReader(raw))
	d.UseNumber()
	var walk func() bool
	walk = func() bool {
		token, err := d.Token()
		if err != nil {
			return false
		}
		switch token {
		case json.Delim('{'):
			seen := map[string]bool{}
			for d.More() {
				k, err := d.Token()
				name, ok := k.(string)
				if err != nil || !ok || seen[name] {
					return false
				}
				seen[name] = true
				if !walk() {
					return false
				}
			}
			last, err := d.Token()
			return err == nil && last == json.Delim('}')
		case json.Delim('['):
			for d.More() {
				if !walk() {
					return false
				}
			}
			last, err := d.Token()
			return err == nil && last == json.Delim(']')
		default:
			_, delim := token.(json.Delim)
			return !delim
		}
	}
	if !walk() {
		return false
	}
	var extra any
	return d.Decode(&extra) == io.EOF
}

func parseRegisteredGateways(raw, identity string) ([]RegisteredGateway, error) {
	if len(raw) > 1<<20 || !uniqueGatewayJSON([]byte(raw)) {
		return nil, fail("openshell_gateways_invalid")
	}
	var rows []map[string]json.RawMessage
	if json.Unmarshal([]byte(raw), &rows) != nil || rows == nil || len(rows) > 128 {
		return nil, fail("openshell_gateways_invalid")
	}
	items := make([]RegisteredGateway, 0, len(rows))
	seen := map[string]bool{}
	active := 0
	for _, fields := range rows {
		var row struct {
			Name, Endpoint string
			Active         *bool
		}
		if json.Unmarshal(fields["name"], &row.Name) != nil || json.Unmarshal(fields["endpoint"], &row.Endpoint) != nil || json.Unmarshal(fields["active"], &row.Active) != nil {
			return nil, fail("openshell_gateways_invalid")
		}
		if !validTaskTarget(row.Name) || seen[row.Name] || row.Active == nil || len(row.Endpoint) > 2048 || validateGatewayEndpoint(row.Endpoint, false) != nil {
			return nil, fail("openshell_gateways_invalid")
		}
		seen[row.Name] = true
		if *row.Active {
			active++
		}
		id := sha256.Sum256([]byte(identity + "\x00" + row.Name))
		fp := sha256.Sum256([]byte(identity + "\x00" + raw + "\x00" + row.Name))
		items = append(items, RegisteredGateway{ID: fmt.Sprintf("og-%x", id[:16]), Name: row.Name, Endpoint: strings.TrimRight(row.Endpoint, "/"), Active: *row.Active, Fingerprint: fmt.Sprintf("%x", fp)})
	}
	if active > 1 {
		return nil, fail("openshell_gateways_invalid")
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Name < items[j].Name })
	return items, nil
}

func (c *Client) gatewayCLIIdentity() (Invocation, string, error) {
	inv, err := c.ResolveInvocation()
	if err != nil || (inv.Source != SourceEnvPair && inv.Source != SourcePath) || !isAbsPath(inv.CLIPath) {
		return inv, "", fail("openshell_gateways_unsupported")
	}
	identity := inv.CLIPath + "\x00" + c.env("HOME") + "\x00" + c.env("XDG_CONFIG_HOME")
	if st, err := os.Stat(inv.CLIPath); err == nil {
		identity += fmt.Sprintf("\x00%d:%d:%d", st.Size(), st.ModTime().UnixNano(), st.Mode())
	} else {
		return inv, "", fail("openshell_gateways_cli_unavailable")
	}
	return inv, identity, nil
}

func (c *Client) DiscoverGateways() GatewayCatalog {
	out := GatewayCatalog{Schema: "local-openshell-gateways/v1", ObservedAt: time.Now().UTC().Format(time.RFC3339Nano), State: "unconfigured", Items: []RegisteredGateway{}}
	if c == nil {
		return out
	}
	inv, identity, err := c.gatewayCLIIdentity()
	if err != nil {
		if inv.Source != SourceNone {
			out.State = "unsupported"
		}
		return out
	}
	out.State = "unavailable"
	raw, err := c.cli("gateway", "list", "--output", "json")
	_, after, identityErr := c.gatewayCLIIdentity()
	if err != nil || identityErr != nil || identity != after {
		return out
	}
	items, err := parseRegisteredGateways(raw, identity)
	if err != nil {
		return out
	}
	out.State, out.Items = "available", items
	return out
}

// selectedGateway returns a fresh client; it never mutates the parent's runtime
// destination or the native CLI's active registration. TLS remains mandatory.
func (c *Client) selectedGateway(id, fp string) (*Client, RegisteredGateway, error) {
	if c == nil || len(id) != 35 || !strings.HasPrefix(id, "og-") || len(fp) != 64 {
		return nil, RegisteredGateway{}, fail("openshell_gateway_selection_changed")
	}
	inv, before, err := c.gatewayCLIIdentity()
	if err != nil {
		return nil, RegisteredGateway{}, err
	}
	cat := c.DiscoverGateways()
	_, after, identityErr := c.gatewayCLIIdentity()
	if cat.State != "available" || identityErr != nil || before != after {
		return nil, RegisteredGateway{}, fail("openshell_gateway_selection_changed")
	}
	for _, row := range cat.Items {
		if row.ID != id || row.Fingerprint != fp {
			continue
		}
		lookup := func(k string) (string, bool) {
			switch k {
			case envCLIBin:
				return inv.CLIPath, true
			case envEndpoint:
				return row.Endpoint, true
			case envGatewayName:
				return row.Name, true
			case envInsecure, envEnvSH:
				return "", false
			default:
				v := c.env(k)
				return v, v != ""
			}
		}
		child := New(Options{LookupEnv: lookup, Timeout: c.Timeout, ProbeTimeout: c.ProbeTimeout, MaxOutput: c.MaxOutput})
		return child, row, nil
	}
	return nil, RegisteredGateway{}, fail("openshell_gateway_selection_changed")
}

func (c *Client) RegisteredGatewayTargets(id, fp string) (GatewayTargets, error) {
	child, row, err := c.selectedGateway(id, fp)
	if err != nil {
		return GatewayTargets{}, err
	}
	catalog := child.DiscoverTargets()
	if _, _, err = c.selectedGateway(id, fp); err != nil || catalog.State == "available" && catalog.Gateway != row.Name {
		return GatewayTargets{}, fail("openshell_gateway_selection_changed")
	}
	return GatewayTargets{Schema: "local-openshell-gateway-targets/v1", ID: id, Fingerprint: fp, Catalog: catalog}, nil
}

func (c *Client) InspectRegisteredGateway(id, fp, target, name, endpointFP string) (GatewayInspection, error) {
	child, row, err := c.selectedGateway(id, fp)
	if err != nil {
		return GatewayInspection{}, err
	}
	inspection, err := child.inspectDiscoveredTarget(target, name, endpointFP, row.Name)
	if err != nil {
		return GatewayInspection{}, err
	}
	if _, _, err = c.selectedGateway(id, fp); err != nil {
		return GatewayInspection{}, err
	}
	return GatewayInspection{Schema: "local-openshell-gateway-inspection/v1", ID: id, Fingerprint: fp, Inspection: inspection}, nil
}
