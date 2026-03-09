up:
	docker compose up --build

up-reverse-ssh:
	docker compose --profile reverse-ssh up --build

test:
	docker compose run --no-deps --rm controller python -m unittest discover -s tests -v

smoke-reverse-ssh:
	./scripts/smoke_reverse_ssh.sh

down:
	docker compose down

config:
	docker compose config

config-reverse-ssh:
	docker compose --profile reverse-ssh config
