package engine

import (
	"go-class-diagram/logging"
	"go-class-diagram/plugin"
)

// Engine orchestrates plugins using Config and Logger.
type Engine struct {
	config  *Config
	logger  logging.Logger
	plugins []plugin.Plugin
}

// NewEngine constructs an Engine.
func NewEngine(cfg *Config, log logging.Logger) *Engine {
	return &Engine{config: cfg, logger: log}
}

// RegisterPlugin adds a plugin.
func (e *Engine) RegisterPlugin(p plugin.Plugin) {
	e.plugins = append(e.plugins, p)
}

// Start initialises and activates all registered plugins.
func (e *Engine) Start() {
	e.logger.Log("Engine starting")
	for _, p := range e.plugins {
		p.Activate()
	}
}
