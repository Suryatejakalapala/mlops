# Docker for ML Services

This document provides instructions for working with Docker in our MLOps project.

## Basic Docker Commands

### Building and Running the Container

```bash
# Build the Docker image
docker build -t ml-service:latest .

# Run the container
docker run -p 5000:5000 ml-service:latest

# Run in detached mode
docker run -d -p 5000:5000 ml-service:latest

# Run with volume mount for development
docker run -d -p 5000:5000 -v $(pwd)/src:/app ml-service:latest
```

### Docker Compose Commands

```bash
# Start services defined in docker-compose.yml
docker-compose up

# Start in detached mode
docker-compose up -d

# Stop services
docker-compose down

# Rebuild services
docker-compose up --build
```

### Container Management

```bash
# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# Stop a container
docker stop <container_id>

# Remove a container
docker rm <container_id>

# List images
docker images

# Remove an image
docker rmi <image_id>
```

### Logging and Debugging

```bash
# View container logs
docker logs <container_id>

# Follow log output
docker logs -f <container_id>

# Execute command inside running container
docker exec -it <container_id> /bin/bash

# Inspect container details
docker inspect <container_id>
```

## Docker Best Practices

1. **Use specific version tags** for base images rather than 'latest' in production
2. **Keep images small** by using Alpine-based images and multi-stage builds
3. **Don't run containers as root** for improved security
4. **Clean up build dependencies** to reduce image size
5. **Use health checks** to monitor container health
6. **Include proper .dockerignore file** to avoid copying unnecessary files
7. **Layer images efficiently** to maximize cache usage
8. **Set environment variables** for configuration
9. **Use volume mounts** for persistent data

## Multi-stage Build Example

For more efficient, production-ready images:

```dockerfile
# Build stage
FROM python:3.9-slim AS builder

WORKDIR /app
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

# Run stage
FROM python:3.9-slim

WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY src/ .

ENV PATH=/root/.local/bin:$PATH
EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
```

## Integration with ML Workflow

- Store trained models as artifacts in a volume mount
- Use environment variables to configure model paths
- Consider using a separate container for model training
- Implement proper versioning for both code and models