FROM alpine:latest

# Install a simple web server
RUN apk add --no-cache lighttpd

# Copy your files (make sure index.html exists in build context)
COPY index.html /var/www/localhost/htdocs/

# Expose port 80
# EXPOSE 80

# Start the web server
CMD ["lighttpd", "-D", "-f", "/etc/lighttpd/lighttpd.conf"]