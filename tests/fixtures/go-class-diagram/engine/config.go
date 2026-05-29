package engine

// Config holds engine configuration.
type Config struct {
	Name       string
	maxThreads int
	DebugMode  bool
}

// Validate checks the configuration.
func (c *Config) Validate() bool {
	return c.Name != "" && c.maxThreads > 0
}
