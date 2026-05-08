package main

import (
	"fmt"
	"strconv"
)

func processData(data string) {
	defer func() {
		recover()
	}()
	panic(data)
}

func ignoreError(s string) int {
	v, _ := strconv.Atoi(s)
	return v
}

func deferInLoop(items []string) {
	for _, item := range items {
		defer fmt.Println(item)
	}
}

func logToStdout(msg string) {
	fmt.Println("DEBUG: " + msg)
}
