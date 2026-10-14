#!/usr/bin/env python3
"""Checks CI runs on this repo: skill frontmatter and names, reference index sync, relative links and
anchors, one version everywhere, and no live ingest values spelled out in skill text. Stdlib only."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REFERENCE_FIELDS = {"title", "impact", "tags"}
IMPACTS = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LINK = re.compile(r"\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6} +(.+?) *$", re.M)
FENCE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1", re.M | re.S)
LIVE_VALUES = re.compile(r"(?:api|otlp|grpc)[a-z.-]*[.]o11y[.]one|x-o11y-key|:431[78]\b", re.I)
SKIP = {".git", "node_modules", "fixtures"}

errors = []


def rel(path):
    return path.relative_to(ROOT).as_posix()


def split_frontmatter(path):
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{rel(path)}: missing frontmatter")
        return "", text
    head, body = text[4:].split("\n---\n", 1)
    return head, body


def top_level(head):
    return dict(re.findall(r"^([A-Za-z-]+):[ \t]*(.*)$", head, re.M))


def slug(heading):
    return re.sub(r"[^a-z0-9 _-]", "", heading.lower()).replace(" ", "-")


def check_skill(skill_dir):
    skill = skill_dir / "SKILL.md"
    if not skill.is_file():
        errors.append(f"{rel(skill_dir)}: no SKILL.md")
        return None
    head, body = split_frontmatter(skill)
    fields = top_level(head)
    for extra in sorted(set(fields) - SKILL_FIELDS):
        errors.append(f"{rel(skill)}: frontmatter field {extra} is not one of the six standard fields")
    name = fields.get("name", "").strip("'\"")
    if not (NAME.match(name) and len(name) <= 64 and name == skill_dir.name):
        errors.append(
            f"{rel(skill)}: name {name!r} must be lowercase letters, digits and single hyphens,"
            f" at most 64 characters, and match the folder {skill_dir.name}"
        )
    description = fields.get("description", "").strip("'\"")
    if description in ("", ">", "|", ">-", "|-") or len(description) > 1024:
        errors.append(f"{rel(skill)}: description must be one non-empty line of at most 1024 characters")
    lines = skill.read_text().count("\n")
    if lines >= 200:
        errors.append(f"{rel(skill)}: {lines} lines; keep SKILL.md under 200")
    references = skill_dir / "references"
    linked = {target.split("#")[0] for target in LINK.findall(body) if target.startswith("references/")}
    present = {f"references/{path.name}" for path in references.glob("*.md")}
    for missing in sorted(linked - present):
        errors.append(f"{rel(skill)} links {missing}, which does not exist")
    for orphan in sorted(present - linked):
        errors.append(f"{rel(skill_dir)}/{orphan} is not linked from SKILL.md")
    for reference in sorted(references.glob("*.md")):
        reference_fields = top_level(split_frontmatter(reference)[0])
        for missing in sorted(REFERENCE_FIELDS - set(reference_fields)):
            errors.append(f"{rel(reference)}: frontmatter lacks {missing}")
        for extra in sorted(set(reference_fields) - REFERENCE_FIELDS):
            errors.append(f"{rel(reference)}: frontmatter field {extra} is not title, impact or tags")
        if "impact" in reference_fields and reference_fields["impact"] not in IMPACTS:
            errors.append(f"{rel(reference)}: impact must be one of {sorted(IMPACTS)}")
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file() and LIVE_VALUES.search(path.read_text()):
            errors.append(f"{rel(path)} spells out a live ingest value; name the MCP tool field instead")
    version = re.search(r"^\s+version:\s*[\"']?([^\"'\s]+)", head, re.M)
    return version.group(1) if version else None


def check_links():
    for doc in sorted(ROOT.rglob("*.md")):
        if SKIP & set(doc.relative_to(ROOT).parts):
            continue
        for target in LINK.findall(doc.read_text()):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target):
                continue
            path_part, _, anchor = target.partition("#")
            dest = (doc.parent / path_part).resolve() if path_part else doc
            if not dest.exists():
                errors.append(f"{rel(doc)}: broken link {target}")
            elif anchor and dest.suffix == ".md" and anchor not in {slug(h) for h in HEADING.findall(FENCE.sub("", dest.read_text()))}:
                errors.append(f"{rel(doc)}: {target} points at a heading that does not exist")


def check_versions(skill_versions):
    found = {"plugin.json": json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text()).get("version")}
    top = re.search(r"^## (\d+\.\d+\.\d+)", (ROOT / "CHANGELOG.md").read_text(), re.M)
    found["CHANGELOG.md"] = top.group(1) if top else None
    found.update(skill_versions)
    if None in found.values() or len(set(found.values())) != 1:
        errors.append(f"versions must match everywhere: {found}")


def main():
    versions = {}
    for skill_dir in sorted(path for path in (ROOT / "skills").iterdir() if path.is_dir()):
        versions[rel(skill_dir / "SKILL.md")] = check_skill(skill_dir)
    check_links()
    check_versions(versions)
    if errors:
        print("\n".join(errors))
        sys.exit(1)
    print(f"ok: {len(versions)} skill(s), links, anchors and versions")


if __name__ == "__main__":
    main()
