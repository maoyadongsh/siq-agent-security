package runtimepath

import "testing"

func TestIdentityDigestMatchesIndependentPythonVector(t *testing.T) {
	s := &Snapshot{path: "C:/范围", device: `\Device\HarddiskVolume3`, exists: true, objects: []identity{
		{volume: 4294967295, indexHigh: 1, indexLow: 2, createdHigh: 3, createdLow: 4, directory: true},
		{volume: 12, indexHigh: 34, indexLow: 56, createdHigh: 78, createdLow: 90},
	}}
	// hashlib.sha256(json.dumps(preimage,ensure_ascii=True,
	// separators=(',',':')).encode()).hexdigest(), independently evaluated.
	want := "aaafe486e481c49dff788cd1f0a70a3c297336252399dfe4af2d1ecbe81f3ae4"
	got, err := s.IdentityDigest()
	if err != nil || got != want {
		t.Fatalf("canonical identity digest: %s %v", got, err)
	}
	s.objects[1].indexLow++
	changed, err := s.IdentityDigest()
	if err != nil || changed == want {
		t.Fatal("file identity omitted from digest")
	}
	if _, err := (*Snapshot)(nil).IdentityDigest(); err != ErrUnverified {
		t.Fatal("empty identity digested")
	}
}
