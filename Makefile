# =============================================================================
# GitLab Infrastructure Project - Makefile
# =============================================================================
# Usage: make <target>
# Run 'make help' to see all available targets

.PHONY: help install test lint format type-check pre-commit \
        docker-build docker-up docker-down docker-logs docker-shell \
        tf-init tf-plan tf-apply tf-destroy \
        clean all

# Default target
.DEFAULT_GOAL := help

# Colors for output
CYAN := \033[36m
GREEN := \033[32m
YELLOW := \033[33m
RESET := \033[0m

# =============================================================================
# Help
# =============================================================================

help: ## Show this help message
	@echo "$(CYAN)GitLab Infrastructure Project$(RESET)"
	@echo ""
	@echo "$(GREEN)Available targets:$(RESET)"
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z_-]+:.*##/ { printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

# =============================================================================
# Python Development (Admin Bot)
# =============================================================================

install: ## Install Python dependencies (dev mode)
	cd gitlab-admin-bot && pip install -e ".[dev]"

test: ## Run pytest test suite
	cd gitlab-admin-bot && pytest tests/ -v

test-cov: ## Run tests with coverage report
	cd gitlab-admin-bot && pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html

lint: ## Run ruff linter
	cd gitlab-admin-bot && ruff check src/ tests/

format: ## Format code with ruff
	cd gitlab-admin-bot && ruff format src/ tests/
	cd gitlab-admin-bot && ruff check --fix src/ tests/

type-check: ## Run mypy type checking
	cd gitlab-admin-bot && mypy src/ --ignore-missing-imports

pre-commit: ## Run all pre-commit hooks
	pre-commit run --all-files

pre-commit-install: ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install

check: lint type-check test ## Run all checks (lint, type-check, test)

# =============================================================================
# Docker (Admin Bot)
# =============================================================================

docker-build: ## Build Docker image
	cd gitlab-admin-bot && docker compose build

docker-up: ## Start containers in background
	cd gitlab-admin-bot && docker compose up -d

docker-down: ## Stop and remove containers
	cd gitlab-admin-bot && docker compose down

docker-logs: ## View container logs (follow mode)
	cd gitlab-admin-bot && docker compose logs -f

docker-shell: ## Open shell in running container
	cd gitlab-admin-bot && docker compose exec admin-bot /bin/bash

docker-restart: docker-down docker-up ## Restart containers

# =============================================================================
# Terraform (Infrastructure)
# =============================================================================

tf-init: ## Initialize Terraform
	cd terraform && terraform init

tf-plan: ## Show Terraform execution plan
	cd terraform && terraform plan

tf-apply: ## Apply Terraform changes
	cd terraform && terraform apply

tf-destroy: ## Destroy Terraform-managed infrastructure
	cd terraform && terraform destroy

tf-fmt: ## Format Terraform files
	cd terraform && terraform fmt -recursive

tf-validate: ## Validate Terraform configuration
	cd terraform && terraform validate

tf-output: ## Show Terraform outputs
	cd terraform && terraform output

# =============================================================================
# Scripts
# =============================================================================

shellcheck: ## Run shellcheck on all scripts
	shellcheck scripts/*.sh

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf gitlab-admin-bot/htmlcov 2>/dev/null || true
	rm -rf gitlab-admin-bot/coverage.xml 2>/dev/null || true

# =============================================================================
# All-in-one targets
# =============================================================================

all: install check ## Install and run all checks

ci: lint type-check test ## Run CI pipeline locally
