"""Utils module"""
from typing import Dict, Iterator

from cmem_plugin_base.dataintegration.entity import Entities
import jinja2


def entities_to_dict(entities: Entities) -> Iterator[Dict[str, str]]:
    """get dict from entities"""
    paths = entities.schema.paths
    for entity in entities.entities:
        result = {}
        for i, path in enumerate(paths):
            result[path.path] = entity.values[i][0] if entity.values[i] else ""
        yield result


def is_string_jinja_template(value: str) -> bool:
    """Check value contain jinja variables"""
    value = value.strip()
    environment = jinja2.Environment(autoescape=True)
    template = environment.from_string(value)
    res = template.render()
    return res != value
