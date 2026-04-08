.PHONY: test lint check docs install clean help check-drift verify ci

help: ## Show this help
	@grep -E '^[a-z_-]+:.*##' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "  %-15s %s\n", $$1, $$2}'

test: ## Run all tests
	python -m pytest tests/ -x -q

lint: ## Run ruff linter
	ruff check src/ tests/

format: ## Format code with ruff
	ruff format src/ tests/

check: ## Run all checks (tests + naming + lint)
	python -m pytest tests/ -x -q
	python scripts/gen_all_variables.py --check
	@echo "All checks passed."

docs: ## Regenerate auto-generated docs
	python scripts/gen_rpc_docs.py
	python scripts/gen_all_variables.py
	python scripts/gen_openapi.py
	python scripts/gen_spec.py

check-drift: ## Check for BGS, declaration, API surface, coverage, concept, and SPEC drift
	python scripts/check_bgs_drift.py
	python scripts/check_coverage.py
	python scripts/check_concepts.py
	python scripts/check_api_surface.py
	python scripts/check_tic_coverage.py
	python scripts/check_spec.py
	python scripts/check_declaration_drift.py || true  # warn but don't fail CI on local declaration drift

verify: check-drift test ## Full verification: check-drift + tests + naming
	python scripts/gen_all_variables.py --check
	@echo "All verification checks passed."

ci: verify lint ## Pre-push gate: verify + lint + format check
	ruff format --check src/ tests/
	@echo "All CI checks passed."

install: ## Install in development mode
	pip install -e .

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ *.egg-info .pytest_cache __pycache__
	find src tests -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .claude/worktrees/
