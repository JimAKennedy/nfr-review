package logging

import "fmt"

// ConsoleLogger implements Logger by writing to stdout.
type ConsoleLogger struct {
	level int
}

// Log writes a message to the console.
func (c *ConsoleLogger) Log(message string) {
	fmt.Println(message)
}

// SetLevel sets the logging level.
func (c *ConsoleLogger) SetLevel(level int) {
	c.level = level
}
