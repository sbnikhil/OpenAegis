.PHONY: help install test lint format clean dev-up dev-down

help:
	@echo "OpenAegis - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  make install       Install dependencies"
	@echo "  make dev-up        Start LocalStack + Prometheus + Grafana"
	@echo "  make dev-down      Stop all services"
	@echo ""
	@echo "Development:"
	@echo "  make format        Format code with black"
	@echo "  make lint          Run linters (ruff, mypy, bandit)"
	@echo "  make test          Run tests with coverage"
	@echo "  make test-unit     Run only unit tests"
	@echo "  make test-int      Run integration tests"
	@echo ""
	@echo "Infrastructure:"
	@echo "  make tf-init       Initialize Terraform"
	@echo "  make tf-plan       Terraform plan"
	@echo "  make tf-apply      Terraform apply"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean         Remove cache and build files"

install:
	pip install -r requirements.txt

dev-up:
	docker-compose up -d
	@echo "Services starting..."
	@echo "LocalStack: http://localhost:4566"
	@echo "Prometheus: http://localhost:9090"
	@echo "Grafana: http://localhost:3000 (admin/admin)"

dev-down:
	docker-compose down

format:
	black src/ tests/
	ruff --fix src/ tests/

lint:
	black --check src/ tests/
	ruff src/ tests/
	mypy src/
	bandit -r src/

test:
	pytest --cov=src --cov-report=html --cov-report=term

test-unit:
	pytest tests/unit/ -v

test-int:
	pytest tests/integration/ -v

tf-init:
	cd terraform && terraform init

tf-plan:
	cd terraform && terraform plan

tf-apply:
	cd terraform && terraform apply

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf dist
	rm -rf build