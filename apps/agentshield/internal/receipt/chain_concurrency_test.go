package receipt

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"testing"

	"siq-agent-security/apps/agentshield/internal/signing"
)

// Exercise the public readers used by status/export and the task snapshot
// while independent callers append. The original implementation races on
// Head and can assign duplicate sequence numbers to concurrent writers.
func TestChainConcurrentSnapshotsAndAppends(t *testing.T) {
	fx := newFixture(t, "block", nil, false)
	c := fx.chain
	cp, err := OpenCheckpointStore(filepath.Dir(filepath.Dir(c.dir)), fx.k)
	if err != nil {
		t.Fatal(err)
	}
	c.AttachCheckpointStore(cp)
	const writers, perWriter = 4, 12
	type tip struct {
		seq  int
		hash string
	}
	var observed []tip
	var tipsMu sync.Mutex
	start, stop := make(chan struct{}), make(chan struct{})
	var readers sync.WaitGroup
	for reader := 0; reader < 4; reader++ {
		readers.Add(1)
		go func(kind int) {
			defer readers.Done()
			<-start
			for {
				select {
				case <-stop:
					return
				default:
				}
				switch kind {
				case 0:
					seq, hash := c.Head()
					tipsMu.Lock()
					observed = append(observed, tip{seq, hash})
					tipsMu.Unlock()
				case 1:
					rows, err := c.Read()
					if err != nil {
						t.Error(err)
						return
					}
					if err := Verify(rows, fx.k.Public()); err != nil {
						t.Error(err)
						return
					}
				case 2:
					read, err := c.ReadLimited(ReadLimit{})
					if err != nil || read.Truncated {
						t.Errorf("bounded read: %v truncated=%v", err, read.Truncated)
						return
					}
					if err := Verify(read.Receipts, fx.k.Public()); err != nil {
						t.Error(err)
						return
					}
				case 3:
					_, projection, err := fx.eng.TaskActivitySnapshot()
					if err != nil {
						t.Error(err)
						return
					}
					if !projection.Verification.PrefixValid {
						t.Error("snapshot prefix invalid")
						return
					}
				}
				runtime.Gosched()
			}
		}(reader)
	}
	var appends sync.WaitGroup
	for writer := 0; writer < writers; writer++ {
		appends.Add(1)
		go func(writer int) {
			defer appends.Done()
			<-start
			for i := 0; i < perWriter; i++ {
				r := Receipt{ReceiptID: fmt.Sprintf("concurrent-%d-%d", writer, i), Action: ActionDeny}
				if err := c.Append(&r); err != nil {
					t.Error(err)
					return
				}
			}
		}(writer)
	}
	close(start)
	appends.Wait()
	close(stop)
	readers.Wait()
	rows, err := c.Read()
	if err != nil || len(rows) != writers*perWriter {
		t.Fatalf("rows=%d err=%v", len(rows), err)
	}
	if err := Verify(rows, fx.k.Public()); err != nil {
		t.Fatal(err)
	}
	for _, head := range observed {
		if head.seq == -1 {
			if head.hash != GenesisPrev {
				t.Fatal("inconsistent empty head")
			}
			continue
		}
		if head.seq < 0 || head.seq >= len(rows) || rows[head.seq].Hash != head.hash {
			t.Fatalf("inconsistent head: %+v", head)
		}
	}
	checkpoint, err := cp.Load(c.ChainID())
	if err != nil || VerifyDetailed(rows, fx.k.Public(), checkpoint).HistoryIntegrity != HistoryVerified {
		t.Fatalf("checkpoint mismatch: %v", err)
	}
	reopened, err := OpenChain(filepath.Dir(filepath.Dir(c.dir)), c.ChainID(), fx.k)
	if err != nil {
		t.Fatal(err)
	}
	seq, hash := reopened.Head()
	if seq != len(rows)-1 || hash != rows[len(rows)-1].Hash {
		t.Fatal("recovery tip mismatch")
	}
}

func TestChainAppendFailurePreservesHeadAndCanRetry(t *testing.T) {
	c, err := OpenChain(t.TempDir(), "local", key(t))
	if err != nil {
		t.Fatal(err)
	}
	day := filepath.Join(c.dir, c.now().Format("2006-01-02")+".jsonl")
	if err := os.Mkdir(day, 0700); err != nil {
		t.Fatal(err)
	}
	if err := c.Append(&Receipt{Action: ActionDeny}); err == nil {
		t.Fatal("expected append failure")
	}
	if seq, head := c.Head(); seq != -1 || head != GenesisPrev {
		t.Fatal("failed write advanced head")
	}
	if err := os.Remove(day); err != nil {
		t.Fatal(err)
	}
	if err := c.Append(&Receipt{Action: ActionDeny}); err != nil {
		t.Fatal(err)
	}
	if seq, _ := c.Head(); seq != 0 {
		t.Fatal("retry did not release lock")
	}
}

// Benchmarks record synchronization overhead separately from durable I/O.
// They are a local comparison, not an end-to-end latency SLA.
func BenchmarkChainSynchronization(b *testing.B) {
	k, err := signing.FromSeed(make([]byte, 32))
	if err != nil {
		b.Fatal(err)
	}
	b.Run("Head", func(b *testing.B) {
		c, err := OpenChain(b.TempDir(), "benchmark", k)
		if err != nil {
			b.Fatal(err)
		}
		b.ResetTimer()
		for i := 0; i < b.N; i++ {
			c.Head()
		}
	})
	b.Run("DurableAppend", func(b *testing.B) {
		c, err := OpenChain(b.TempDir(), "benchmark", k)
		if err != nil {
			b.Fatal(err)
		}
		b.ResetTimer()
		for i := 0; i < b.N; i++ {
			if err := c.Append(&Receipt{Action: ActionDeny}); err != nil {
				b.Fatal(err)
			}
		}
	})
}
