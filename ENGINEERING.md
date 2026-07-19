# Engineering Guide

Engineering principles, coding standards and development workflow for the Bergen Platform.

---

# Purpose

The Bergen Platform is designed to be a long-lived, reproducible and fully automated infrastructure platform.

This document defines the engineering rules that every playbook, role and contribution must follow.

The primary goals are:

- Readability
- Maintainability
- Reproducibility
- Idempotency
- Automation
- Consistency

Whenever there is a conflict between writing less code and writing clearer code, clarity wins.

---

# Engineering Principles

## Idempotency

Every playbook and role shall be safely executable multiple times.

Running the same playbook repeatedly must never introduce configuration drift.

Every task should report **changed** only when the managed system has actually changed.

---

## Declarative Infrastructure

Infrastructure is described as desired state.

Playbooks describe *what* the final system shall look like.

Implementation details belong inside roles.

---

## Single Responsibility

Every role has exactly one responsibility.

Examples:

- podman
- ollama
- open-webui
- redis
- postgresql

Roles should never configure unrelated services.

---

## Modular Design

Large roles are split into task files.

Typical execution flow:

install
↓
directories
↓
configure
↓
service
↓
api
↓
validate

Each file should perform one logical task.

---

## Validation First

Every playbook validates its required variables before provisioning begins.

Configuration errors should fail immediately with clear messages.

---

## Runtime Discovery

Whenever possible, runtime information is queried from the target system instead of being assumed.

Examples:

- assigned IPv4 address
- generated MAC address
- effective bridge
- service status

---

## Least Privilege

Only execute tasks with elevated privileges when required.

Avoid permanent root execution whenever possible.

---

## Documentation

Every role contains:

README.md

describing

- purpose
- installed software
- generated files
- provided services
- validation

---

# Repository Layout

The project root contains platform documentation.

README.md
ARCHITECTURE.md
ENGINEERING.md
CHANGELOG.md
SECURITY.md
UPDATE.md
BACKUP.md
TROUBLESHOOTING.md

Automation resides below:

ansible/

---

# Ansible Role Standard

Every role follows the same layout.

README.md
defaults/
files/
handlers/
meta/
tasks/
templates/
vars/

The tasks directory is split into logical task files.

Example:

install.yml
directories.yml
configure.yml
service.yml
api.yml
validate.yml

tasks/main.yml only imports these task files.

---

# Playbook Standard

Every playbook follows the same high-level structure.

Validation

Provisioning

Runtime discovery

Validation

Summary

The final task should present a human-readable summary.

---

# Naming Conventions

Playbooks

bootstrap-*.yml

create-*.yml

validate-*.yml

Roles

lowercase

hyphen-separated

Variables

snake_case

Inventory groups

snake_case

Task names should clearly describe their purpose.

---

# Git Workflow

Use small commits.

One logical change per commit.

Follow Conventional Commits.

Examples:

feat:
fix:
refactor:
docs:
test:
chore:

Infrastructure changes should be committed separately from code changes whenever practical.

---

# Testing

Every new role should pass:

ansible-playbook --syntax-check

successful execution

second execution without unexpected changes

validation tasks

---

# Future Tooling

The following tools are planned:

ansible-lint

yamllint

Molecule

GitHub Actions

pre-commit

Automated documentation validation

---

# Philosophy

The Bergen Platform should remain understandable years after its creation.

Engineering decisions should always favour:

clarity over cleverness

explicit over implicit

simple over complex

automation over manual work

consistency over individual preference

