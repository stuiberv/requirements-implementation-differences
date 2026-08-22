import argparse
import subprocess
import tempfile
from llm.agent_factory import create_llm_client
from pathlib import Path

def clone_repo(repo_url: str) -> Path:
    temp_dir = Path(tempfile.mkdtemp())

    print(f"Cloning repository: {repo_url}")
    print(f"Working directory: {temp_dir}")

    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(temp_dir)],
        check=True,
    )

    return temp_dir

def get_repo_structure(base_dir: Path) -> str:
    lines = []

    for path in sorted(base_dir.rglob("*")):
        if ".git" in path.parts:
            continue

        relative_path = path.relative_to(base_dir)

        if path.is_dir():
            lines.append(f"[DIR]  {relative_path}")
        else:
            lines.append(f"[FILE] {relative_path}")

    return "\n".join(lines)


def read_file(base_dir: Path, relative_path: str) -> str:
    file_path = base_dir / relative_path

    print(f"Reading: {relative_path}")

    return file_path.read_text(encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Compare requirements with implementation in a GitHub repository."
    )

    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository URL",
    )

    parser.add_argument(
        "--requirements",
        required=True,
        help="Path to the requirements file inside the repository",
    )

    parser.add_argument(
        "--implementation",
        nargs="+",
        required=True,
        help="One or more implementation files inside the repository",
    )

    args = parser.parse_args()

    repo_dir = clone_repo(args.repo)

    repository_structure = get_repo_structure(repo_dir)

    requirements = read_file(repo_dir, args.requirements)

    implementation_parts = []

    for implementation_file in args.implementation:
        content = read_file(repo_dir, implementation_file)

        implementation_parts.append(
            f"""
    FILE: {implementation_file}

    {content}
    """
        )

    implementation_text = "\n".join(implementation_parts)

    instructions = Path(
        "instructions/requirements-validator.md"
    ).read_text(encoding="utf-8")

    input_text = f"""
    REPOSITORY STRUCTURE

    {repository_structure}

    REQUIREMENTS

    {requirements}

    IMPLEMENTATION

    {implementation_text}
    """

    print("\n=== DATA PREPARED FOR LLM ===")
    print(input_text)

    llm = create_llm_client("openai")

    print("\n=== CALLING LLM ===")

    result = llm.validate(
        instructions=instructions,
        input_text=input_text,
    )

    print("\n=== VALIDATION RESULT ===")
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()