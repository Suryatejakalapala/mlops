.PHONY: test lint package clean

test:
	pytest

lint:
	ruff check .

# Build the Lambda deployment zip consumed by Terraform (var.lambda_package_path).
# Installs the package + runtime deps from pyproject.toml — one source of truth.
package: clean
	mkdir -p dist/build
	pip install . -t dist/build --quiet
	cd dist/build && zip -qr ../ade-lambda.zip . -x '*.pyc' -x '*__pycache__*' -x '*.dist-info/*'
	@echo "Built dist/ade-lambda.zip"

clean:
	rm -rf dist
