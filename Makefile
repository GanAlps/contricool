.DEFAULT_GOAL := help

# Stub target list. Real implementations land in later phases — see specs/EXECUTION_PLAN.md.

.PHONY: help bootstrap dev-up api-test client-test infra-diff infra-deploy-dev openapi openapi-check lint format

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

client-test: ## Run client tests with coverage  [Phase 2+]
	@echo "Not yet implemented (Phase 2+)."
	@exit 1

infra-diff: ## Show CDK diff against deployed stacks  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

infra-deploy-dev: ## Deploy CDK stacks to dev (CI-only, never from a laptop for prod)  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

openapi: ## Regenerate openapi.yaml + client-sdk types  [Phase 2+]
	@echo "Not yet implemented (Phase 2+)."
	@exit 1

openapi-check: ## Verify checked-in openapi.yaml matches API code  [Phase 2+]
	@echo "openapi-check: no-op until Phase 2."
	@exit 0

lint: ## Run ruff + mypy + biome + tsc on the workspace  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1

format: ## Auto-format with ruff + biome  [Phase 1+]
	@echo "Not yet implemented (Phase 1+)."
	@exit 1
