package main

import (
	"fmt"
	"log"
)

func stdoutLogging() {
	fmt.Println("debug info")
	fmt.Printf("value: %d\n", 42)
	fmt.Print("raw output")
}

func stdlibLogging() {
	log.Println("log message")
	log.Printf("formatted: %s", "data")
	log.Print("plain log")
	log.Fatal("fatal error")
	log.Fatalf("fatal: %v", "err")
}
