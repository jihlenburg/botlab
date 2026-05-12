# =============================================================================
# GitLab Infrastructure Project - Makefile
# =============================================================================
# Usage: make <target>
# Run 'make help' to see all available targets

.PHONY: help \
        tf-init tf-plan tf-apply tf-destroy tf-fmt tf-validate tf-output \
        seed-validate seed-generate seed-diff \
        shellcheck \
        pre-commit pre-commit-install \
        clean ci

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
# Seed Configuration
# =============================================================================

seed-validate: ## Validate seed.yaml
	python scripts/seed_bootstrap.py seed.yaml --validate

seed-generate: ## Generate all config files from seed.yaml
	python scripts/seed_bootstrap.py seed.yaml --target all

seed-diff: ## Show diff of what seed would generate vs existing files
	python scripts/seed_bootstrap.py seed.yaml --target all --diff

# =============================================================================
# Scripts
# =============================================================================

shellcheck: ## Run shellcheck on all scripts (requires shellcheck installed)
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck scripts/*.sh; else echo "shellcheck not installed, skipping"; fi

# =============================================================================
# Pre-commit
# =============================================================================

pre-commit: ## Run all pre-commit hooks
	pre-commit run --all-files

pre-commit-install: ## Install pre-commit hooks
	pip install pre-commit
	pre-commit install

# =============================================================================
# Cleanup
# =============================================================================

clean: ## Clean up generated caches
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# =============================================================================
# All-in-one targets
# =============================================================================

ci: shellcheck tf-fmt tf-validate ## Run CI pipeline locally
