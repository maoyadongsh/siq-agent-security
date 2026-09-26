package main

import (
	"context"
	"errors"
	"flag"
	"log"
	"runtime"
	"time"
)

// serve owns both periodic loops. Cancellation waits for active work to stop
// before releasing the device lock; it never enrolls or changes permissions.
func cmdServe(ctx context.Context, args []string) error {
	fs := flag.NewFlagSet("serve", flag.ContinueOnError)
	if err := fs.Parse(args); err != nil {
		if errors.Is(err, flag.ErrHelp) {
			return nil
		}
		return err
	}
	if fs.NArg() != 0 {
		return errors.New("serve accepts no positional arguments")
	}
	if runtime.GOOS != "linux" {
		return errors.New("serve currently requires Linux")
	}
	state, err := LoadState()
	if err != nil {
		return err
	}
	release, err := acquireTaskLock()
	if err != nil {
		return err
	}
	defer release()
	client := newAuthedClient(state)
	heartbeat := initialScanHeartbeat(state, measureServiceCapabilities, client.HeartbeatWithCapabilities, client.RequestInitialScan)
	heartbeat, err = scheduledHeartbeat(state, client, heartbeat)
	if err != nil {
		return err
	}
	return serveLoops(ctx, heartbeat, func(ctx context.Context) error {
		return executePendingTasks(ctx, state, client)
	}, 30*time.Second, 15*time.Minute)
}

func serveLoops(ctx context.Context, heartbeat, tasks func(context.Context) error, interval, maximum time.Duration) error {
	if interval <= 0 || maximum < interval {
		return errors.New("invalid serve interval")
	}
	done := make(chan struct{}, 2)
	for _, work := range []func(context.Context) error{heartbeat, tasks} {
		go func(work func(context.Context) error) {
			defer func() { done <- struct{}{} }()
			delay := interval
			for ctx.Err() == nil {
				err := work(ctx)
				if ctx.Err() != nil {
					return
				}
				if err == nil {
					delay = interval
				} else {
					// Do not echo upstream bodies, URLs or credentials into service logs.
					log.Print("edge service operation failed; bounded retry scheduled")
				}
				timer := time.NewTimer(delay)
				select {
				case <-ctx.Done():
					timer.Stop()
					return
				case <-timer.C:
				}
				if err != nil {
					if delay >= maximum/2 {
						delay = maximum
					} else {
						delay *= 2
					}
				}
			}
		}(work)
	}
	<-done
	<-done
	return nil
}
