.DEFAULT_GOAL := help

# Stub target list. Real implementations land in later phases — see specs/EXECUTION_PLAN.md.

.PHONY: help bootstrap dev-up api-test client-test client-dev client-build client-lint client-typecheck infra-diff infra-deploy-dev openapi openapi-check lint format

help: ## Show this help
	@awk 'BEGIN{FS=":.*?## "} /^[a-zA-Z_-]+:.*?##/ {printf "  \033[1m%-22s\033[0m %s\n", $$1, $$2}' Makefile

bootstrap: ## Install dependencies and git hooks (run once after clone)
	pnpm install
	pnpm exec lefthook install

dev-up: ## Start local dev stack (LocalStack + API + Expo)  [Phase 1+]
	@echo "Not yet implemented (Phase 1+). See specs/EXECUTION_PLAN.md."
	@exit 1

api-test: ## Run API tests with coverage  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

client-test: ## Run client tests with coverage
	pnpm --filter @contricool/client test:coverage

client-dev: ## Start the Expo client dev server (web)
	pnpm --filter @contricool/client dev:web

client-build: ## Build the Expo client web bundle
	pnpm --filter @contricool/client build:web

client-lint: ## Run Biome lint+format check on the client
	pnpm --filter @contricool/client lint

client-typecheck: ## Run TypeScript typecheck on the client
	pnpm --filter @contricool/client typecheck

infra-diff: ## Show CDK diff against deployed stacks  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

infra-deploy-dev: ## Deploy CDK stacks to dev (CI-only, never from a laptop for prod)  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

openapi: ## Regenerate openapi.yaml + client-sdk schema types
	cd apps/api && /home/oshogupta/workspace/master-venv/bin/python scripts/emit_openapi.py
	pnpm --filter @contricool/client-sdk build

openapi-check: ## Drift-check the committed openapi.yaml vs the FastAPI app
	cd apps/api && /home/oshogupta/workspace/master-venv/bin/python scripts/emit_openapi.py --check

lint: ## Run ruff + mypy + biome + tsc on the workspace  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

format: ## Auto-format with ruff + biome  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1
