package main

import (
	"errors"
	"log"
)

func safeParse(data string) error {
	if data == "" {
		return errors.New("empty data")
	}
	log.Printf("processing: %s", data)
	return nil
}
