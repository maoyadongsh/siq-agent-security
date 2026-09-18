package openshell

import (
	"encoding/json"
	"io"
	"regexp"
	"strings"
)

var sandboxUUID = regexp.MustCompile(`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)

type sandboxLoadRow struct {
	ID                   string      `json:"id"`
	Name                 string      `json:"name"`
	Phase                string      `json:"phase"`
	CurrentPolicyVersion json.Number `json:"current_policy_version"`
}

// sandboxLoadedInstance reads the gateway's current sandbox resource. In the
// pinned v0.0.83 protocol, current_policy_version advances when the sandbox
// reports a loaded policy; Ready is the gateway's runtime readiness summary.
// Neither value alone is a load proof, so callers also require the exact
// policy get --full revision/digest/Loaded marker from the same CLI endpoint.
func (c *Client) sandboxLoadedInstance(target, revision string) (string, error) {
	out, err := c.cli("sandbox", "list", "--limit", "1000", "--output", "json")
	if err != nil {
		return "", err
	}
	decoder := json.NewDecoder(strings.NewReader(out))
	decoder.UseNumber()
	var rows []sandboxLoadRow
	if err := decoder.Decode(&rows); err != nil || len(rows) > 1000 {
		return "", fail(errTaskPolicyNotLoaded)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return "", fail(errTaskPolicyNotLoaded)
	}
	var id string
	for _, row := range rows {
		if row.Name != target {
			continue
		}
		if id != "" || !sandboxUUID.MatchString(row.ID) || row.Phase != "Ready" ||
			row.CurrentPolicyVersion.String() != revision {
			return "", fail(errTaskPolicyNotLoaded)
		}
		id = row.ID
	}
	if id == "" {
		return "", fail(errTaskPolicyNotLoaded)
	}
	return id, nil
}

// CurrentTaskSandboxID is a read-only gateway observation for constructing
// and rechecking a human-approved task binding. The returned UUID is advisory
// until the caller binds it to a signed decision and checks it again before
// spawn. A name alone is never an instance identity.
func (c *Client) CurrentTaskSandboxID(target, revision string) (string, error) {
	if !c.taskBackendBound() {
		return "", fail(errTaskBackendUnbound)
	}
	return c.sandboxLoadedInstance(target, revision)
}
