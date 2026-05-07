variable "instance_type" {
  type        = string
  description = "EC2 instance type"
  default     = "t2.micro"
}

variable "environment" {
  type        = string
  description = "Deployment environment"
  default     = "dev"
}
