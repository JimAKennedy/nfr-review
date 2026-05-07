package main

import (
	"context"
	"net/http"
	"sync"
	"time"
)

func properErrorHandling() error {
	resp, err := http.Get("http://example.com")
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	return nil
}

func contextAwareGoroutine(ctx context.Context) {
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		select {
		case <-ctx.Done():
			return
		default:
		}
	}()
	wg.Wait()
}

func httpClientWithTimeout() {
	client := &http.Client{Timeout: 30 * time.Second}
	resp, err := client.Get("http://example.com")
	if err != nil {
		return
	}
	defer resp.Body.Close()
}

func deferOutsideLoop() {
	defer cleanup()
}

func cleanup() {}
