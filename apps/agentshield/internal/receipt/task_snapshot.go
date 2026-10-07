package receipt

import "errors"

// TaskActivitySnapshot serializes the ledger read with engine appends. Budgets
// never turn a partial history into a successful task projection.
func (e *Engine) TaskActivitySnapshot() ([]Receipt, TaskActivities, error) {
	e.mu.Lock()
	defer e.mu.Unlock()
	chain := e.opts.Chain
	chain.mu.RLock()
	defer chain.mu.RUnlock()
	read, err := chain.readLimitedLocked(ReadLimit{})
	if err != nil || read.Truncated {
		return nil, TaskActivities{}, errors.New("task activities: snapshot unavailable or over budget")
	}
	seq, tip := -1, GenesisPrev
	if len(read.Receipts) > 0 {
		last := read.Receipts[len(read.Receipts)-1]
		seq, tip = last.Seq, last.Hash
	}
	if seq != chain.seq || tip != chain.head {
		return nil, TaskActivities{}, errors.New("task activities: snapshot head mismatch")
	}
	var checkpoint *Checkpoint
	if chain.cpStore != nil {
		checkpoint, err = chain.cpStore.LoadOptional(chain.chainID)
		if err != nil {
			return nil, TaskActivities{}, errors.New("task activities: checkpoint unavailable")
		}
	}
	projected, err := ProjectTaskActivities(read.Receipts, chain.key.Public(), checkpoint)
	return read.Receipts, projected, err
}
