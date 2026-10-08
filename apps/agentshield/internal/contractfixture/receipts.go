// Package contractfixture provides comparisons for signed receipt test vectors.
// It is only consumed by tests and does not verify or authorize receipts.
package contractfixture

import (
	"bytes"
	"encoding/json"
	"errors"
	"strconv"
)

// EqualReceiptContent compares all fields except generated identities and the
// chain hashes/signatures that depend on them. Callers MUST independently verify
// both original chains before using this comparison. References are mapped to
// row positions, preserving their relationships rather than discarding them.
func EqualReceiptContent(actual, historical []byte) (bool, error) {
	left, err := normalized(actual)
	if err != nil {
		return false, err
	}
	right, err := normalized(historical)
	return err == nil && bytes.Equal(left, right), err
}

func normalized(raw []byte) ([]byte, error) {
	var rows []map[string]any
	if err := json.Unmarshal(raw, &rows); err != nil {
		var single map[string]any
		if err = json.Unmarshal(raw, &single); err != nil {
			return nil, err
		}
		rows = []map[string]any{single}
	}
	ids := make(map[string]string, len(rows))
	for i, row := range rows {
		id, ok := row["receipt_id"].(string)
		if !ok || id == "" || ids[id] != "" {
			return nil, errors.New("fixture: missing or duplicate receipt identity")
		}
		ids[id] = "fixture-row-" + strconv.Itoa(i)
	}
	for _, row := range rows {
		row["receipt_id"] = ids[row["receipt_id"].(string)]
		if id, ok := row["decision_receipt_id"].(string); ok && ids[id] != "" {
			row["decision_receipt_id"] = ids[id]
		}
		if hold, ok := row["hold"].(map[string]any); ok {
			if id, ok := hold["resolved_by_receipt_id"].(string); ok && ids[id] != "" {
				hold["resolved_by_receipt_id"] = ids[id]
			}
		}
		delete(row, "hash")
		delete(row, "prev_hash")
		delete(row, "sig")
	}
	return json.Marshal(rows)
}
