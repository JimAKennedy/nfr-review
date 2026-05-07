package main

import (
	"fmt"
	"net/http"
	"os"
	"strconv"
)

func discardErrorWithBlank() {
	_, _ = fmt.Println("hello")
}

func discardErrorShortVar() {
	resp, _ := http.Get("http://example.com")
	_ = resp
}

func completelyDiscardReturn() {
	http.Get("http://example.com/discard")
}

func multipleIgnored() {
	f, _ := os.Open("/tmp/test")
	_ = f
	_, _ = strconv.Atoi("not-a-number")
}
