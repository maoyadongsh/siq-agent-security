// Synthetic protocol helper, never a signed production Edge release.
package main

import (
	"fmt"
	"os"
)

func main() {
	if len(os.Args) != 2 || os.Args[1] != "upgrade-capabilities" || os.Getenv("SIQ_EDGE_STATE_DIR") != "" || os.Getenv("HOME") != "" {
		os.Exit(4)
	}
	fmt.Println(`{"schema_version":"enterprise-upgrade-capabilities/v1","version":"probe-fixture","pending_protocol":"enterprise-upgrade-pending/v1","confirmation_protocol":"enterprise-upgrade-intent/v1","task_lock":true}`)
}
