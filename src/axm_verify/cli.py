import json
from pathlib import Path
import click
from .logic import verify_shard

@click.group()
def main():
    pass

@main.command("shard")
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=Path))
def shard_cmd(path: Path):
    result = verify_shard(path)
    click.echo(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))

if __name__ == "__main__":
    main()
