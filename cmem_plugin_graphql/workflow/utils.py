"""Utils module"""
import json
import uuid
from typing import Dict, Iterator, Any, List, Set, Optional

from cmem_plugin_base.dataintegration.entity import (
    Entities,
    Entity,
    EntityPath,
    EntitySchema,
)
import jinja2


def get_dict(entities: Entities) -> Iterator[Dict[str, str]]:
    """get dict from entities"""
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


def get_entities_from_list(data: List[Dict[str, Any]]) -> Entities:
    """generate entities from list"""
    paths: List[str] = []
    unique_paths: Set[str] = set()
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


def create_entity(paths: List[str], dict_: Dict[str, Any]) -> Entity:
    """Create entity from dict based on order from paths list"""
    values: List[List[Optional[str]]] = []
    for path in paths:
        value = dict_.get(path)
        if value is None:
            values.append([])
        elif type(value) in (int, float, bool, str):
            values.append([value])
        else:
            values.append([json.dumps(value)])
    entity_uri = f"urn:uuid:{str(uuid.uuid4())}"
    return Entity(uri=entity_uri, values=values)
