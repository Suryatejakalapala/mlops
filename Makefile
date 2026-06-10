.PHONY: test lint package clean

test:
	pytest tests/ -q

lint:
	ruff check ade/ tests/

# Build the Lambda deployment zip consumed by Terraform (var.lambda_package_path).
package: clean
	mkdir -p dist/build
	pip install -r ade/requirements.txt -t dist/build --quiet
	cp -r ade dist/build/ade
	cd dist/build && zip -qr ../ade-lambda.zip . -x '*.pyc' -x '*__pycache__*'
	@echo "Built dist/ade-lambda.zip"

clean:
	rm -rf dist
