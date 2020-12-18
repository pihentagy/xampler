import datetime
import functools
import logging
import random
import string
from typing import *

import lxml.etree as ET
import rstr
import xmlschema

MAX_REPEAT = 100
INDENT_SHIFT = 4


@functools.lru_cache
def indent(num):
    return ' ' * INDENT_SHIFT * num


@functools.lru_cache
def num_parents(node):
    return sum(1 for _ in node.iterancestors())


def indent_for(node):
    return indent(num_parents(node))


ts_min = int(datetime.datetime(1970, 1, 1).timestamp())
ts_max = int(datetime.datetime(2050, 1, 1).timestamp())

primitive_values = {
    '{http://www.w3.org/2001/XMLSchema}dateTime':
        lambda: datetime.datetime.fromtimestamp(random.randint(ts_min, ts_max)).strftime('%Y-%m-%dT%H:%M:%SZ'),
    '{http://www.w3.org/2001/XMLSchema}string':
        lambda: rstr.rstr(string.ascii_letters + string.digits + string.punctuation, 2000),
    '{http://www.w3.org/2001/XMLSchema}int':
        lambda: random.randint(-2 ** 31, 2 ** 31),
    '{http://www.w3.org/2001/XMLSchema}decimal':
        lambda: random.uniform(-1e32, 1e32)
}
restrictions = {
    'XsdMaxLengthFacet': lambda v: rstr.rstr(string.ascii_letters, 0, v.value),
    'XsdEnumerationFacets': lambda v: random.choice(v.enumeration),
}


def gen_nodes(
        root_xsd_node: xmlschema.XsdElement,
        dest_root: ET.Element,
        repetitions: Dict = None,
        value_generators: Dict[str, Callable[[str, ET.Element], Any]] = None,
        type_generators: Dict[str, Callable[[], Any]] = None,
        element_hook: Callable[[ET.Element], Dict] = None):
    def default_element_hook(_):
        return {}

    if repetitions is None:
        repetitions = {}
    if value_generators is None:
        value_generators = {}
    if type_generators is None:
        type_generators = {}
    if element_hook is None:
        element_hook = default_element_hook

    def _gen_nodes(xsd_node: xmlschema.XsdElement, dest_elem: ET.Element, extra_data: Dict):
        """
        Handles repetition of the node
        :param dest_elem:
        """
        min_occ, max_occ = xsd_node.min_occurs, xsd_node.max_occurs

        tag_name = xsd_node.local_name
        if tag_name in repetitions:
            repeat = repetitions[tag_name](extra_data)
        else:
            if max_occ is None:
                repeat = 2  # random.randint(min_occ, MAX_REPEAT)
            else:
                repeat = random.randint(min_occ, max_occ)

        logging.info(f'{indent_for(dest_elem)}<!-- {xsd_node.local_name} {repeat} ({min_occ}-{max_occ}) -->')
        if xsd_node.annotation:
            logging.info(
                f'{indent_for(dest_elem)}<!--{" ".join(d.text for d in xsd_node.annotation.documentation)} -->')

        for i in range(repeat):
            logging.info(f'{indent_for(dest_elem)}<{xsd_node.local_name}>[{i}]')
            new_element = ET.SubElement(dest_elem, xsd_node.local_name)
            extra_dict = element_hook(new_element)
            if extra_dict:
                extra_data = {**extra_data, **extra_dict}
            gen_node(xsd_node, new_element, extra_data)
            logging.info(f'{indent_for(dest_elem)}</{xsd_node.local_name}>')

    def gen_node(node: xmlschema.XsdElement, dest_elem, extra_data):
        """
        Generates one node, handling complex/simple node type
        """
        if node.type.has_complex_content():
            assert node.type.content.model == 'sequence'
            for n in node.type.content:
                _gen_nodes(n, dest_elem, extra_data)
        else:
            for attr_name in node.attributes:
                attr = node.attributes[attr_name]
                if attr.is_prohibited() or attr.is_optional() and random.randrange(2):
                    continue
                attr_value = value_generator(node.attributes[attr_name], dest_elem, extra_data)
                dest_elem.set(attr_name, str(attr_value))
            value = value_generator(node, dest_elem, extra_data)
            dest_elem.text = str(value)

    def value_generator(xsd_elem, node, extra_data):
        n = xsd_elem.local_name
        if isinstance(xsd_elem, xmlschema.validators.XsdAttribute):
            n = node.tag + '@' + n
        if n in value_generators:
            return value_generators[n](extra_data, node)
        else:
            return by_type_value_generator(xsd_elem)

    def by_type_value_generator(xsd_elem):
        """
        Generates one value (result is string or numeric)
        Works for:
        * atomic types
        * restrictions
        * complex types with attr_name simple value
        """
        if not xsd_elem.type.is_simple():
            assert xsd_elem.type.has_simple_content()
            return generate_by_type(xsd_elem.type.content)
        elif xsd_elem.type.is_restriction():
            return generate_by_restriction(xsd_elem)
        elif xsd_elem.type.is_atomic():
            return generate_by_type(xsd_elem.type)
        else:
            raise TypeError('Unknown type', xsd_elem.type)

    def generate_by_restriction(xsd_elem):
        if len(xsd_elem.type.validators) == 0:  # no validator, just return default
            return generate_by_type(xsd_elem.type.base_type)
        elif len(xsd_elem.type.validators) > 1:
            raise ValueError('Cannot handle more restrictions')
        else:
            v = xsd_elem.type.validators[0]
            return restrictions[type(v).__name__](v)

    def generate_by_type(atomic_type):
        # TODO type specific custom generator
        n = atomic_type.name
        if n in type_generators:
            return type_generators[n]()
        else:
            return primitive_values[n]()

    _gen_nodes(root_xsd_node, dest_root, {})


'''
TODO
- missing types
- missing restrictions
- option for mandatory only (only generate mandatory tags)
- validate generated values
- validate generated restrictions
- can attributes have newlines?
'''
