package main

import "net/http"

func defaultClientGet() {
	resp, err := http.Get("http://example.com")
	_ = resp
	_ = err
}

func defaultClientPost() {
	resp, err := http.Post("http://example.com", "application/json", nil)
	_ = resp
	_ = err
}

func defaultClientHead() {
	resp, err := http.Head("http://example.com")
	_ = resp
	_ = err
}

func defaultClientPostForm() {
	resp, err := http.PostForm("http://example.com", nil)
	_ = resp
	_ = err
}

func clientWithoutTimeout() {
	client := &http.Client{}
	_ = client
}

func clientWithTimeout() {
	client := &http.Client{Timeout: 30}
	_ = client
}
