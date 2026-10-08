package server

// These counters describe promotion attempts, never authority or effect proof.
// They intentionally exclude raw errors and unsigned event content.
type pendingPromotionStatus struct {
	Status       string `json:"status"`
	Attempts     uint64 `json:"attempts"`
	Failures     uint64 `json:"failures"`
	LastPromoted int    `json:"last_promoted"`
}

func (s *Server) pendingPromotionSnapshot() pendingPromotionStatus {
	s.pendingMu.Lock()
	defer s.pendingMu.Unlock()
	snapshot := s.pendingState
	if snapshot.Status == "" {
		snapshot.Status = "unknown"
	}
	return snapshot
}
