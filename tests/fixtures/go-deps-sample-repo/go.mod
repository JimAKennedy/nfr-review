module github.com/example/sample-app

go 1.21

require (
	github.com/gin-gonic/gin v1.9.1
	golang.org/x/net v0.17.0 // indirect
	github.com/stretchr/testify v1.8.4
)

require github.com/google/uuid v1.4.0

replace github.com/old/module => github.com/new/module v1.0.0
