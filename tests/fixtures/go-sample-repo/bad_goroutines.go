package main

import "fmt"

func bareGoroutineLiteral() {
	go func() {
		fmt.Println("bare goroutine")
	}()
}

func bareGoroutineCall() {
	go doWork()
}

func multipleGoroutines() {
	go processItem()
	go func() {
		fmt.Println("another one")
	}()
}
