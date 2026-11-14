variable "values" {
  description = "Arguments of ARM uniqueString(); joined with \"-\" like ARM does. Printable ASCII, at most 256 characters in total."
  type        = list(string)

  validation {
    condition     = length(join("-", var.values)) <= 256 && length(regexall("[^ -~]", join("-", var.values))) == 0
    error_message = "uniqueString input must be printable ASCII and at most 256 characters."
  }
}
