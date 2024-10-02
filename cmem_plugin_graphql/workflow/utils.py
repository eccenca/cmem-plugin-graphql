"""Utils module"""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import jinja2
from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntityPath,
    EntitySchema,
)


def get_dict(entities: Entities) -> Iterator[dict[str, str]]:
    """Get dict from entities"""
    paths = entities.schema.paths
    for entity in entities.entities:
        result = {}
        for i, path in enumerate(paths):
            result[path.path] = entity.values[i][0] if entity.values[i] else ""
        yield result


def is_jinja_template(value: str) -> bool:
    """Check value contain jinja variables"""
    environment = jinja2.Environment(autoescape=True)
    template = environment.from_string(value)
    res = template.render()
    return res != value


def get_entities_from_list(data: list[dict[str, Any]]) -> Entities:
    """Generate entities from list"""
    paths: list[str] = []
    unique_paths: set[str] = set()
    entities = []
    # first pass to extract paths
    for dict_ in data:
        unique_paths.update(set(dict_.keys()))

    paths = list(unique_paths)
    for dict_ in data:
        entity = create_entity(paths, dict_)
        entities.append(entity)

    schema = EntitySchema(
        type_uri="https://example.org/vocab/RandomValueRow",
        paths=[EntityPath(path=path) for path in paths],
    )
    return Entities(entities=entities, schema=schema)


def create_entity(paths: list[str], dict_: dict[str, Any]) -> Entity:
    """Create entity from dict based on order from paths list"""
    values: list[list[str | None]] = []
    for path in paths:
        value = dict_.get(path)
        if value is None:
            values.append([])
        elif type(value) in (int, float, bool, str):
            values.append([value])
        else:
            values.append([json.dumps(value)])
    entity_uri = f"urn:uuid:{uuid.uuid4()!s}"
    return Entity(uri=entity_uri, values=values)
