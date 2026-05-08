package main

import "fmt"

func deferInForLoop() {
	for i := 0; i < 10; i++ {
		defer fmt.Println(i)
	}
}

func deferInRangeLoop() {
	items := []string{"a", "b", "c"}
	for _, item := range items {
		defer fmt.Println(item)
	}
}

func deferOutsideLoop() {
	defer fmt.Println("cleanup")
}
