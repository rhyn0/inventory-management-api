# inventory-management-api
Project with Python and PostgreSQL to model an inventory tracking system

<p align="center">
<a href="https://github.com/tiangolo/fastapi/" target="_blank">
    <img src="https://img.shields.io/badge/-FastAPI-D77310?style=flat&logo=fastapi&logoColor=009688" alt="FastAPI">
</a>
<img src="https://img.shields.io/badge/-PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=ffdd54" alt="PostgreSQL">
<a href="https://www.sqlalchemy.org/" target="_blank">
    <img src="https://img.shields.io/badge/-SQLAlchemy-8a251e" alt="SQLAlchemy">
</a>
<a href="https://pypi.org/project/fastapi" target="_blank">
    <img src="https://img.shields.io/badge/-Docker-D77310?style=flat&logo=docker&logoColor=2496ED" alt="Docker">
</a>
<a href="https://docs.astral.sh/ruff/" target="_blank">
    <img src="https://img.shields.io/badge/-Ruff-D77310?style=flat&logo=ruff&logoColor=FCC21B" alt="Ruff">
</a>
</p>

## Todo of Features

[ ] IaC to deploy to *Production*\
[ ] [Docker Compose File](https://www.educative.io/blog/docker-compose-tutorial)
[ ] Change HTTPException details to be more like FastAPI
[ ] Update request and response models to be more JSON like - camelCase

## Purpose

Design and create a REST API using [FastAPI](https://fastapi.tiangolo.com/) and [SQLAlchemy](https://www.sqlalchemy.org/). A quick step into a using an ASGI framework and explore the rich typing system that both projects have made use of.

## Code

### Environment Management

Currently tool of choice for Python environments is [Poetry](https://python-poetry.org/). This makes it simple to handle version pinning and even packaging as needed.

```bash
# Get started by installing a virtual env
poetry install
# Activate venv
poetry shell
# or use the venv Python without activation
poetry run python ...
```

### Format and Lint

[Black](https://black.readthedocs.io/en/stable/) has been a great formatter for all of my projects and this one is no different.
[Ruff](https://docs.astral.sh/ruff/) has been a great addition to Python projects, yet again showing a great integration of Python and Rust.

These are run on the code in this project using [pre-commit](https://pre-commit.com/). To enforce that usage:

```bash
# Make sure that dependencies have been previously installed
poetry run pre-commit install
poetry run pre-commit run --all-files
```

## Quickstart

### Test Locally

Since this does rely on PostgreSQL, it is better to run it as-is using [Docker Compose](https://docs.docker.com/compose/). But you can edit the app to use a SQLite connection string `./inven_api/common/.env.db`.

```bash
# edit DB connection string
vim ./inven_api/common/.env.db
poetry run uvicorn main:APP
```

### From a Docker Container

```bash
docker-compose up --build
```


## Development

### Start PostgreSQL container

Instead of using *latest* which at this time is 16, going to use 15.4 for this project.

Start the Postgres container for dev with:

`docker run --name postgres-dev -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:15.4`

### Connect to Postgres via psql

Then once the container is started, we can use `psql` for any later debugging to test our code executions.

We need to specify localhost in this case, otherwise `psql` will try to use the default machine socket that isn't present due to the container running.

`psql -h localhost -U postgres -W`

### Initialize the Database Tables

It is better to call the **SQLAlchemy** `Base.metadata.create_all` from a seperate script and not tie it to the server start up. I think it makes more sense to have a seperate script to do that.

```bash
python3 create_database.py
```
