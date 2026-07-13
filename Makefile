# Convenience wrapper for build / deploy / local-test.
# Override IMAGE/STACK as needed:  make build IMAGE=ghcr.io/jsaumer/jellyfin-recs:latest

IMAGE   ?= ghcr.io/jsaumer/jellyfin-recs:$(shell cat VERSION 2>/dev/null || echo latest)
STACK   ?= jellyfin-recs
COMPOSE ?= docker compose
PYTHONPATH_SRC := PYTHONPATH=src

.PHONY: help build push deploy redeploy logs test lint clean up down \
        version tag release-patch release-minor release-major

help:
	@echo "Targets:"
	@echo "  build     Build the Docker image ($(IMAGE))"
	@echo "  push      Push the image to its registry"
	@echo "  deploy    docker stack deploy -c deploy/docker-compose.yaml $(STACK)"
	@echo "  redeploy  Force a rolling update of the running service"
	@echo "  logs      Follow the service logs"
	@echo "  up        Local test via deploy/compose.local.yml (uses .env)"
	@echo "  down      Stop the local compose stack"
	@echo "  test      Run the smoke tests (no Docker needed)"
	@echo "  lint      Byte-compile all Python + validate YAML/sh"
	@echo "  version   Print the current version"
	@echo "  tag       Git-tag the current VERSION"
	@echo "  release-{patch,minor,major}  Bump VERSION"

build:
	docker build -t $(IMAGE) .

push:
	docker push $(IMAGE)

deploy:
	IMAGE=$(IMAGE) docker stack deploy -c deploy/docker-compose.yaml $(STACK)

redeploy:
	docker service update --force $(STACK)_$(STACK)

logs:
	docker service logs -f $(STACK)_$(STACK)

up:
	$(COMPOSE) -f deploy/compose.local.yml up --build

down:
	$(COMPOSE) -f deploy/compose.local.yml down

test:
	$(PYTHONPATH_SRC) python3 tests/smoke_test.py

lint:
	@python3 -c "import py_compile,glob; [py_compile.compile(f,doraise=True) for f in glob.glob('src/jellyfin_recs/*.py')+glob.glob('tests/*.py')]; print('python OK')"
	@python3 -c "import yaml; [yaml.safe_load(open(f)) for f in ['deploy/docker-compose.yaml','deploy/compose.local.yml']]; print('yaml OK')"
	@sh -n deploy/entrypoint.sh && echo "entrypoint OK"

clean:
	rm -rf __pycache__ src/jellyfin_recs/__pycache__ tests/__pycache__ data .seeded *.pyc

# ---- Versioning ------------------------------------------------------------
VERSION := $(shell cat VERSION 2>/dev/null || echo 0.0.0)

version:
	@echo $(VERSION)

tag:
	git tag -a v$(VERSION) -m "Release v$(VERSION)"
	@echo "Tagged v$(VERSION). Push with: git push origin v$(VERSION)"

release-patch:
	@python3 -c "v=open('VERSION').read().strip().split('.'); v[2]=str(int(v[2])+1); open('VERSION','w').write('.'.join(v)); print('->', '.'.join(v))"

release-minor:
	@python3 -c "v=open('VERSION').read().strip().split('.'); v[1]=str(int(v[1])+1); v[2]='0'; open('VERSION','w').write('.'.join(v)); print('->', '.'.join(v))"

release-major:
	@python3 -c "v=open('VERSION').read().strip().split('.'); v[0]=str(int(v[0])+1); v[1]='0'; v[2]='0'; open('VERSION','w').write('.'.join(v)); print('->', '.'.join(v))"
