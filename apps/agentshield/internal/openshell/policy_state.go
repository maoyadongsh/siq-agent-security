package openshell

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"sync"

	"siq-agent-security/apps/agentshield/internal/canon"
)

const operationRegistryLimit = 256

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
}

func newPolicyCoordinator() *policyCoordinator {
	return &policyCoordinator{operations: make(map[string]policyOperation)}
}

var processPolicyCoordinator = newPolicyCoordinator()

func (c *Client) targetPolicyLock(target string) *sync.Mutex {
	sum := sha256.Sum256([]byte(target))
	return &c.policy.locks[int(sum[0])%len(c.policy.locks)]
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
