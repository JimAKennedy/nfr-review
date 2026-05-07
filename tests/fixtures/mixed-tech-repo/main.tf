resource "aws_instance" "app" {
  ami           = "ami-0c55b159cbfafe1f0"
  instance_type = "t2.micro"

  tags = {
    Name = "app-server"
  }
}

resource "aws_s3_bucket" "data" {
  bucket = "my-app-data"
}
