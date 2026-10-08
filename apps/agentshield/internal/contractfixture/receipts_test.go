package contractfixture

import "testing"

func TestReceiptComparisonPreservesAuthorityAndReferenceDifferences(t *testing.T) {
	old := []byte(`[{"receipt_id":"old","action":"hold","hash":"old-hash","sig":"old-sig"},{"receipt_id":"old-res","decision_receipt_id":"old","action":"allow"}]`)
	current := []byte(`[{"receipt_id":"new","action":"hold","hash":"new-hash","sig":"new-sig"},{"receipt_id":"new-res","decision_receipt_id":"new","action":"allow"}]`)
	if same, err := EqualReceiptContent(current, old); err != nil || !same {
		t.Fatal("identity-only change rejected", err)
	}
	for _, changed := range []string{
		`[{"receipt_id":"new","action":"allow"},{"receipt_id":"new-res","decision_receipt_id":"new","action":"allow"}]`,
		`[{"receipt_id":"new","action":"hold"},{"receipt_id":"new-res","decision_receipt_id":"new-res","action":"allow"}]`,
		`[{"receipt_id":"new","action":"hold"},{"receipt_id":"new-res","decision_receipt_id":"unknown","action":"allow"}]`,
		`[{"receipt_id":"new","action":"hold","authority_status":"valid"},{"receipt_id":"new-res","decision_receipt_id":"new","action":"allow"}]`,
	} {
		if same, err := EqualReceiptContent([]byte(changed), old); err != nil || same {
			t.Fatal("semantic change was hidden by identity normalization", err)
		}
	}
}

func TestReceiptComparisonRejectsDuplicateIdentities(t *testing.T) {
	raw := []byte(`[{"receipt_id":"duplicate"},{"receipt_id":"duplicate"}]`)
	if _, err := EqualReceiptContent(raw, raw); err == nil {
		t.Fatal("duplicate identity accepted as a stable fixture")
	}
}
