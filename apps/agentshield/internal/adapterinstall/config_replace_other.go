//go:build !windows

package adapterinstall

func configPublishBusy(error, string) bool { return false }
