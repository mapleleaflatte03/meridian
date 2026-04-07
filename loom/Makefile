ROOT ?= $(CURDIR)
KERNEL_PATH ?= /opt/meridian-kernel
LOOM ?= $(ROOT)/target/release/loom
LOOM_ROOT ?= $(HOME)/.local/share/meridian-loom/runtime/default
SERVICE_TOKEN ?= loom-local-token
HTTP_ADDRESS ?= 127.0.0.1:8080
ORG_ID ?= local_foundry
RELEASE_DIR ?= $(ROOT)/dist
PREFIX ?= $(HOME)/.local/share/meridian-loom

.PHONY: build test init doctor health status start stop restart logs run-local package-release release-local docker-build docker-up docker-down install-local acceptance acceptance-container acceptance-shadow-zk acceptance-shadow-zk-embodied acceptance-shadow-zk-lane acceptance-swarm-zk-lane acceptance-memory-graph-lane acceptance-init-nation-lane acceptance-breed-lane acceptance-embodied-physical-lane acceptance-connect-lane acceptance-connect-ecosystem-lane acceptance-connect-failure-injection-lane acceptance-connect-security-lane acceptance-connect-c2-matrix-lane acceptance-connect-telegram-lane acceptance-connect-discord-lane acceptance-connect-whatsapp-lane acceptance-connect-slack-lane acceptance-connect-email-lane acceptance-connect-browser-lane acceptance-connect-shell-lane acceptance-connect-desktop-lane acceptance-connect-webhook-lane acceptance-migration-profile-lane acceptance-extension-lane acceptance-quickstart-lane acceptance-deploy-lane acceptance-security-auth-lane acceptance-observability-lane acceptance-observe-stream-lane acceptance-oss-dx-lane acceptance-branding-lane connect-kpi-gate dev-first-proof verify-release

build:
	cargo build --release --workspace --locked

test:
	cargo test --workspace

init: build
	$(LOOM) init --mode embedded --root "$(LOOM_ROOT)" --kernel-path "$(KERNEL_PATH)" --org-id "$(ORG_ID)"

doctor:
	$(LOOM) doctor --root "$(LOOM_ROOT)" --format human

health:
	$(LOOM) health --root "$(LOOM_ROOT)" --format human

status:
	$(LOOM) status --root "$(LOOM_ROOT)"

start: build
	$(LOOM) init --mode embedded --root "$(LOOM_ROOT)" --kernel-path "$(KERNEL_PATH)" --org-id "$(ORG_ID)" || true
	$(LOOM) start --root "$(LOOM_ROOT)" --kernel-path "$(KERNEL_PATH)" --http-address "$(HTTP_ADDRESS)" --service-token "$(SERVICE_TOKEN)" --max-jobs 1 --poll-seconds 1 --iterations 1000000 --format human

stop:
	$(LOOM) stop --root "$(LOOM_ROOT)" --format human

restart: stop start

logs:
	$(LOOM) logs --root "$(LOOM_ROOT)" --follow

run-local:
	$(MAKE) init
	$(MAKE) start

package-release:
	./scripts/package_release.sh --kernel-path "$(KERNEL_PATH)" --output-dir "$(RELEASE_DIR)"

release-local:
	./scripts/release_local.sh --kernel-path "$(KERNEL_PATH)" --output-dir "$(RELEASE_DIR)"

docker-build:
	docker build -t meridian-loom:local .

docker-up:
	@if docker compose version >/dev/null 2>&1; then \
		docker compose up --build; \
	elif command -v docker-compose >/dev/null 2>&1; then \
		docker-compose up --build; \
	else \
		echo "docker compose is unavailable on this host; use ./scripts/acceptance_container_service.sh or direct docker run instead" >&2; \
		exit 2; \
	fi

docker-down:
	@if docker compose version >/dev/null 2>&1; then \
		docker compose down; \
	elif command -v docker-compose >/dev/null 2>&1; then \
		docker-compose down; \
	else \
		echo "docker compose is unavailable on this host; no compose stack to stop" >&2; \
		exit 2; \
	fi

install-local:
	./scripts/install_local.sh "$(RELEASE_DIR)" --prefix "$(PREFIX)"

acceptance:
	./scripts/acceptance_local_service.sh --root "$(LOOM_ROOT)" --kernel-path "$(KERNEL_PATH)"

acceptance-container:
	./scripts/acceptance_container_service.sh --kernel-path "$(KERNEL_PATH)"

acceptance-shadow-zk:
	./scripts/acceptance_shadow_zk.sh

acceptance-shadow-zk-embodied:
	./scripts/acceptance_shadow_embodied_zk.sh

acceptance-shadow-zk-lane:
	./scripts/acceptance_shadow_zk_lane.sh

acceptance-swarm-zk-lane:
	./scripts/acceptance_swarm_zk_lane.sh

acceptance-memory-graph-lane:
	./scripts/acceptance_memory_graph_lane.sh

acceptance-init-nation-lane:
	./scripts/acceptance_init_nation_lane.sh

acceptance-breed-lane:
	./scripts/acceptance_breed_lane.sh

acceptance-embodied-physical-lane:
	./scripts/acceptance_embodied_physical_lane.sh

acceptance-connect-lane:
	./scripts/acceptance_connect_lane.sh

acceptance-connect-ecosystem-lane:
	./scripts/acceptance_connect_ecosystem_lane.sh

acceptance-connect-failure-injection-lane:
	./scripts/acceptance_connect_failure_injection_lane.sh

acceptance-connect-security-lane:
	./scripts/acceptance_connect_security_lane.sh

acceptance-connect-c2-matrix-lane:
	./scripts/acceptance_connect_c2_matrix_lane.sh

acceptance-connect-telegram-lane:
	./scripts/acceptance_connect_telegram_lane.sh

acceptance-connect-discord-lane:
	./scripts/acceptance_connect_discord_lane.sh

acceptance-connect-whatsapp-lane:
	./scripts/acceptance_connect_whatsapp_lane.sh

acceptance-connect-slack-lane:
	./scripts/acceptance_connect_slack_lane.sh

acceptance-connect-email-lane:
	./scripts/acceptance_connect_email_lane.sh

acceptance-connect-browser-lane:
	./scripts/acceptance_connect_browser_lane.sh

acceptance-connect-shell-lane:
	./scripts/acceptance_connect_shell_lane.sh

acceptance-connect-desktop-lane:
	./scripts/acceptance_connect_desktop_lane.sh

acceptance-connect-webhook-lane:
	./scripts/acceptance_connect_webhook_lane.sh

acceptance-migration-profile-lane:
	./scripts/acceptance_migration_profile_lane.sh

acceptance-extension-lane:
	./scripts/acceptance_extension_lane.sh

acceptance-quickstart-lane:
	./scripts/acceptance_quickstart_lane.sh

acceptance-deploy-lane:
	./scripts/acceptance_deploy_lane.sh

acceptance-security-auth-lane:
	./scripts/acceptance_security_auth_lane.sh

acceptance-observability-lane:
	./scripts/acceptance_observability_lane.sh

acceptance-observe-stream-lane:
	./scripts/acceptance_observe_stream_lane.sh

acceptance-oss-dx-lane:
	./scripts/acceptance_oss_dx_lane.sh

acceptance-branding-lane:
	./scripts/acceptance_branding_lane.sh

connect-kpi-gate:
	./scripts/connect_kpi_gate.sh --root "$(LOOM_ROOT)" --adapter-id telegram-adapter --adapter-id discord-adapter --adapter-id browser-adapter --adapter-id shell-adapter --adapter-id desktop-adapter --adapter-id webhook-adapter

dev-first-proof:
	./scripts/dev_first_proof.sh

verify-release:
	./scripts/verify_release_local.sh --kernel-path "$(KERNEL_PATH)"
