.PHONY: up down restart logs ps setup process-test clean

# Start all services
up:
	docker-compose up -d --remove-orphans

# Stop all services
down:
	docker-compose down

# Restart services
restart:
	docker-compose restart

# View logs
logs:
	docker-compose logs -f

# Show service status
ps:
	docker-compose ps

# Run the setup check (cli version)
setup:
	docker exec -it bexio-receipts-app-1 bexio-receipts setup

# Process the sample receipt to test the pipeline
process-test:
	docker exec -it bexio-receipts-app-1 bexio-receipts process tests/fixtures/sample_receipt.png --dry-run

# Clean up temporary files
clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__ src/bexio_receipts/__pycache__ tests/__pycache__
	docker-compose down -v
