package openshell

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"sync"
	"time"

	"siq-agent-security/apps/agentshield/internal/canon"
)

const (
	operationRegistryLimit = 256
	// A successful --wait is an observation, not a durable capability. Require
	// a recent observation before a task starts even when the readback bytes
	// and Loaded marker have remained unchanged.
	loadedPolicyMaxAge = 5 * time.Minute
)

type policyOperation struct {
	ID              string
	Target          string
	Base            Snapshot
	AppliedRevision string
	AppliedDigest   string
	NoOp            bool
}

type policyCoordinator struct {
	locks          [64]sync.Mutex
	operationsMu   sync.Mutex
	operations     map[string]policyOperation
	operationOrder []string
	// Loaded facts come from either a successful policy set --wait or a fresh
	// combination of policy get --full and the gateway's Ready/current-policy
	// sandbox observation. ReadEffective alone cannot create one. They are
	// process-local, bounded, and invalidated on inconsistency or unknown write.
	loaded map[string]loadedPolicy
	// An invalidated revision cannot be silently repaired by old bytes. A
	// different revision may establish a new proof from both gateway readbacks;
	// an unknown prior revision requires an explicit successful --wait.
	invalidated map[string]string
}

type loadedPolicy struct {
	revision    string
	digest      string
	loadEpoch   string
	sandboxID   string
	confirmedAt time.Time
}

func newPolicyCoordinator() *policyCoordinator {
	return &policyCoordinator{operations: make(map[string]policyOperation), loaded: make(map[string]loadedPolicy), invalidated: make(map[string]string)}
}

var processPolicyCoordinator = newPolicyCoordinator()

func (c *Client) targetPolicyLock(target string) *sync.Mutex {
	sum := sha256.Sum256([]byte(target))
	return &c.policy.locks[int(sum[0])%len(c.policy.locks)]
}

func (c *Client) loadedPolicyKey(target string) string {
	return c.InvocationFingerprint() + "\x00" + target
}

func (c *Client) forgetLoadedPolicy(target string) {
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	key := c.loadedPolicyKey(target)
	old := c.policy.loaded[key]
	delete(c.policy.loaded, key)
	if c.policy.invalidated == nil {
		c.policy.invalidated = make(map[string]string)
	}
	if _, alreadyInvalidated := c.policy.invalidated[key]; !alreadyInvalidated {
		c.policy.invalidated[key] = old.revision
	}
}

func (c *Client) rememberLoadedPolicy(target, revision, digest, loadEpoch string) {
	if loadEpoch == "" {
		return
	}
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	if c.policy.loaded == nil {
		c.policy.loaded = make(map[string]loadedPolicy)
	}
	key := c.loadedPolicyKey(target)
	c.policy.loaded[key] = loadedPolicy{
		revision: revision, digest: digest, loadEpoch: loadEpoch, confirmedAt: time.Now(),
	}
	delete(c.policy.invalidated, key)
}

// confirmOrObserveLoadedPolicy accepts a fresh gateway-reported load fact only
// when no previous fact was invalidated in this process. A --wait fact without
// an instance ID gets bound to the first matching live sandbox observation.
func (c *Client) confirmOrObserveLoadedPolicy(target, revision, digest, loadEpoch, sandboxID string) bool {
	if loadEpoch == "" || sandboxID == "" {
		return false
	}
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	key := c.loadedPolicyKey(target)
	if invalidatedRevision, wasInvalidated := c.policy.invalidated[key]; wasInvalidated {
		if invalidatedRevision == "" || invalidatedRevision == revision {
			return false
		}
		// The old proof stays dead. A different, monotonically reported
		// loaded revision gets a fresh proof only from the current policy and
		// sandbox readbacks; no old approval can match the new revision.
		delete(c.policy.invalidated, key)
	}
	if c.policy.loaded == nil {
		c.policy.loaded = make(map[string]loadedPolicy)
	}
	loaded, ok := c.policy.loaded[key]
	if !ok {
		c.policy.loaded[key] = loadedPolicy{
			revision: revision, digest: digest, loadEpoch: loadEpoch,
			sandboxID: sandboxID, confirmedAt: time.Now(),
		}
		return true
	}
	if loaded.revision != revision && loaded.sandboxID == sandboxID {
		c.policy.loaded[key] = loadedPolicy{
			revision: revision, digest: digest, loadEpoch: loadEpoch,
			sandboxID: sandboxID, confirmedAt: time.Now(),
		}
		return true
	}
	if loaded.revision != revision || loaded.digest != digest || loaded.loadEpoch != loadEpoch ||
		(loaded.sandboxID != "" && loaded.sandboxID != sandboxID) ||
		loaded.confirmedAt.IsZero() || time.Since(loaded.confirmedAt) >= loadedPolicyMaxAge {
		return false
	}
	if loaded.sandboxID == "" {
		loaded.sandboxID = sandboxID
		c.policy.loaded[key] = loaded
	}
	return true
}

func policyDigest(policy map[string]any) (string, error) {
	raw, err := canon.Marshal(policy)
	if err != nil {
		return "", fail("策略包含无法规范化的值（fail-closed）")
	}
	sum := sha256.Sum256(raw)
	return hex.EncodeToString(sum[:]), nil
}

func staticPolicyDigest(policy map[string]any) (string, error) {
	static := clonePolicy(policy)
	delete(static, "network_policies")
	return policyDigest(static)
}

func clonePolicy(src map[string]any) map[string]any {
	out := make(map[string]any, len(src))
	for key, value := range src {
		out[key] = clonePolicyValue(value)
	}
	return out
}

func clonePolicyValue(value any) any {
	switch typed := value.(type) {
	case map[string]any:
		return clonePolicy(typed)
	case []any:
		out := make([]any, len(typed))
		for i := range typed {
			out[i] = clonePolicyValue(typed[i])
		}
		return out
	default:
		return typed
	}
}

func newOperationID() (string, error) {
	var raw [24]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", fail("无法生成策略操作身份（fail-closed）")
	}
	return "opo-" + hex.EncodeToString(raw[:]), nil
}

func (c *Client) rememberOperation(op policyOperation) {
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	for len(c.policy.operationOrder) >= operationRegistryLimit {
		oldest := c.policy.operationOrder[0]
		c.policy.operationOrder = c.policy.operationOrder[1:]
		delete(c.policy.operations, oldest)
	}
	c.policy.operations[op.ID] = op
	c.policy.operationOrder = append(c.policy.operationOrder, op.ID)
}

func (c *Client) lookupOperation(id string) (policyOperation, bool) {
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	op, ok := c.policy.operations[id]
	return op, ok
}

func (c *Client) consumeOperation(id string) {
	c.policy.operationsMu.Lock()
	defer c.policy.operationsMu.Unlock()
	delete(c.policy.operations, id)
	for i, candidate := range c.policy.operationOrder {
		if candidate == id {
			c.policy.operationOrder = append(c.policy.operationOrder[:i], c.policy.operationOrder[i+1:]...)
			break
		}
	}
}

func validateReceiptBinding(receipt DeploymentReceipt, op policyOperation, target string) error {
	if receipt.OperationID == "" || receipt.OperationID != op.ID || receipt.Target != target || op.Target != target ||
		receipt.BaseRevision != op.Base.Revision || receipt.BasePolicyDigest != op.Base.PolicyDigest ||
		receipt.BackendRevision != op.AppliedRevision || receipt.AppliedPolicyDigest != op.AppliedDigest {
		return fail("策略回滚回执与可信操作记录不匹配（fail-closed）")
	}
	wantResult := "applied"
	if op.NoOp {
		wantResult = "no_op"
	}
	if receipt.Result != wantResult {
		return fail("策略回滚回执与可信操作记录不匹配（fail-closed）")
	}
	return nil
}
