package server

import (
	"fmt"
	"net/http"

	"siq-agent-security/apps/agentshield/internal/receipt"
)

// uniqueReceiptByID returns the only receipt with this ID from an already
// verified chain. A repeated ID is not a choice between records: callers must
// fail closed instead of using the first or last match.
func uniqueReceiptByID(chain []receipt.Receipt, id string) (*receipt.Receipt, error) {
	if id == "" {
		return nil, fmt.Errorf("openshell_receipt_ambiguous")
	}
	var found *receipt.Receipt
	for i := range chain {
		if chain[i].ReceiptID != id {
			continue
		}
		if found != nil {
			return nil, fmt.Errorf("openshell_receipt_ambiguous")
		}
		found = &chain[i]
	}
	return found, nil
}

func bindingStatus(err error) int {
	if err == nil {
		return http.StatusOK
	}
	if err.Error() == "openshell_receipt_ambiguous" || err.Error() == "openshell_task_instance_unconfirmed" {
		return http.StatusConflict
	}
	return http.StatusForbidden
}

func taskLookupStatus(errCode string) int {
	switch errCode {
	case "openshell_task_reservation_unknown":
		return http.StatusNotFound
	case "openshell_receipt_ambiguous":
		return http.StatusConflict
	default:
		return http.StatusServiceUnavailable
	}
}
