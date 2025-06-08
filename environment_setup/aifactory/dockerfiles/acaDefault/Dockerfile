# Use a base image you've already pulled locally
FROM alpine:latest

# Copy your files
COPY index.html /index.html

# Dont Expose port 80 or any other port
# If you want to expose a port, uncomment the line below
# EXPOSE 80

# Use a command that exists in alpine
CMD ["cat", "/index.html"]