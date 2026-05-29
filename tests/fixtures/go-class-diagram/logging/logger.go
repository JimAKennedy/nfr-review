package logging

// Logger is the logging interface.
type Logger interface {
	Log(message string)
	SetLevel(level int)
}
