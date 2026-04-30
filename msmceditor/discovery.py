"""World discovery — scan a server directory for editable Java/Bedrock worlds."""

from pathlib import Path


def discover_worlds(server_path):
    """
    Find editable worlds in a server directory.
    Returns list of {name, path, platform, hasDimensions}.
    """
    worlds = []
    server_path = Path(server_path)
    if not server_path.is_dir():
        return worlds

    for item in server_path.iterdir():
        if not item.is_dir():
            continue
        # Java world: directory containing level.dat
        if (item / 'level.dat').exists():
            has_dims = (
                (item / 'DIM-1').is_dir()
                or (item / 'DIM1').is_dir()
                or (item / 'dimensions').is_dir()
            )
            worlds.append({
                'name': item.name,
                'path': str(item),
                'platform': 'java',
                'hasDimensions': has_dims,
            })

    return worlds
