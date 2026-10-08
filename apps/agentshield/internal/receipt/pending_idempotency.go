package receipt

import (
	"bytes"
	"encoding/json"
	"errors"
)

// Called with Engine.mu held; chain verification does not mutate the log.
// Historical duplicates are a semantic ambiguity, not a new signature failure.
func (e *Engine) findPromotedPending(candidate Receipt, legacyID string) (*Receipt, error) {
	var found *Receipt
	legacyAmbiguous := false
	err := e.opts.Chain.walkVerified(func(record Receipt) error {
		if record.ReceiptID == candidate.ReceiptID {
			if found != nil || !samePendingPayload(record, candidate) {
				return errors.New("receipt: pending source semantic conflict")
			}
			value := record
			found = &value
		}
		if record.ReceiptID == legacyID && samePendingPayload(record, candidate) {
			legacyAmbiguous = true
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	if found != nil {
		return found, nil
	}
	if legacyAmbiguous {
		return nil, errors.New("receipt: historical pending source ambiguous")
	}
	return nil, nil
}

func samePendingPayload(a, b Receipt) bool {
	if a.SchemaVersion != b.SchemaVersion || a.RecordType != b.RecordType ||
		a.Action != b.Action || a.Platform != b.Platform || a.SessionID != b.SessionID ||
		a.Tool != b.Tool || a.ParamsDigest != b.ParamsDigest || a.Reason != b.Reason ||
		a.EnforcementMode != b.EnforcementMode {
		return false
	}
	left, err := json.Marshal(a.LocalOrigin)
	if err != nil {
		return false
	}
	right, err := json.Marshal(b.LocalOrigin)
	return err == nil && bytes.Equal(left, right)
}
