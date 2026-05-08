package main

import "fmt"

func recoverWithoutRethrow() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Println("recovered:", r)
		}
	}()
	panic("oops")
}

func recoverWithRethrow() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Println("recovered and rethrowing:", r)
			panic(r)
		}
	}()
	panic("oops")
}

func multipleRecovers() {
	defer func() {
		if r := recover(); r != nil {
			fmt.Println("first recover")
		}
	}()
	defer func() {
		if r := recover(); r != nil {
			panic(r)
		}
	}()
}
